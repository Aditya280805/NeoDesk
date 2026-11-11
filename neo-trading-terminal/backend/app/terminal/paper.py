from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from app.terminal.store import now
from app.terminal.catalogue import contract_open


def paise(value):
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        raise ValueError('Price must be a positive finite number.')
    return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


class PaperAccount:
    """
    Simulated trading account for paper trading.
    
    Handles virtual balances, margin requirements, and order matching against 
    real-time market data without executing trades on the actual broker.
    """
    FUTURES_MARGIN_RATE = Decimal('0.20')

    def __init__(self, store):
        """Initialize the PaperAccount with the database store."""
        self.store = store

    def submit(
        self,
        instrument=None,
        side=None,
        quantity=None,
        order_type='MARKET',
        price=None,
        request_id=None,
        quote=None,
        user_id=None,
        *args,
        **kwargs
    ):
        if isinstance(instrument, int):
            actual_user_id = instrument
            actual_instrument = side
            actual_side = quantity
            actual_quantity = order_type
            actual_order_type = price if price is not None else 'MARKET'
            actual_price = request_id
            actual_request_id = quote
            actual_quote = args[0] if args else kwargs.get('quote')
            user_id = actual_user_id
            instrument = actual_instrument
            side = actual_side
            quantity = actual_quantity
            order_type = actual_order_type
            price = actual_price
            request_id = actual_request_id
            quote = actual_quote
        else:
            if user_id is None:
                user_id = kwargs.get('user_id', 1)

        if user_id is None or isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ValueError('Valid user account is required.')
        if not isinstance(instrument, dict):
            raise ValueError('Valid instrument is required.')
        if side not in ('BUY', 'SELL'):
            raise ValueError("Order side must be 'BUY' or 'SELL'.")
        if order_type not in ('MARKET', 'LIMIT'):
            raise ValueError("Order type must be 'MARKET' or 'LIMIT'.")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError('Quantity must be a positive integer.')
        if order_type == 'LIMIT' and price is None:
            raise ValueError('A limit order needs a limit price.')

        if not contract_open(instrument):
            raise ValueError('This contract has expired or its expiry is unknown. Choose an active contract.')
        if instrument['kind']=='FUTURE':
            return self._future_order(user_id,instrument,side,quantity,order_type,request_id,quote)
        if instrument['kind'] not in ('EQUITY', 'ETF', 'OPTION'):
            raise ValueError('This cash-funded simulator supports stocks, ETFs and long options. Index levels and futures cannot be bought here.')
        if quantity < 1 or quantity % instrument['lot_size']:
            raise ValueError(f"Quantity must be a multiple of {instrument['lot_size']}.")
        if quantity > 10000:
            raise ValueError('Maximum quantity is 10,000 units per order.')
        current = paise(quote['ltp'])
        limit = paise(price) if order_type == 'LIMIT' else None
        tick = paise(instrument['tick_size'])
        if limit and limit % tick:
            raise ValueError(f"Limit price must follow tick size {instrument['tick_size']}.")
        fill = order_type == 'MARKET' or (side == 'BUY' and current <= limit) or (side == 'SELL' and current >= limit)
        requested = (instrument['id'], side, quantity, order_type, limit)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM orders WHERE user_id=? AND request_id=?', (user_id,request_id)).fetchone()
            if existing:
                if tuple(existing[k] for k in ('instrument_id', 'side', 'quantity', 'order_type', 'limit_price')) != requested:
                    raise ValueError('This request identifier was already used for a different order.')
                return dict(existing)
            source_key='paper_source' if user_id==1 else f'paper_source:{user_id}'
            source = db.execute('SELECT value FROM metadata WHERE key=?',(source_key,)).fetchone()
            if source and source[0] != quote['source']:
                raise ValueError('This paper account uses another data source. Reconnect it or reset the account before switching.')
            reserve = current if fill else limit
            if reserve * quantity > 50000000:
                raise ValueError('Maximum paper order value is ₹5,00,000.')
            self._capacity(db, user_id, instrument['id'], side, quantity, reserve)
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (source_key,quote['source']))
            identifier = 'P-' + uuid4().hex[:12].upper()
            db.execute('INSERT INTO orders (id, user_id, request_id, instrument_id, side, quantity, order_type, limit_price, fill_price, status, created_at, filled_at, source, symbol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                identifier, user_id, request_id, instrument['id'], side, quantity, order_type, limit,
                current if fill else None, 'FILLED' if fill else 'OPEN', now(), now() if fill else None,
                quote['source'], instrument['symbol']))
            if fill:
                self._fill(db, user_id, instrument['id'], side, quantity, current)
            db.execute('INSERT INTO audit(user_id,created_at,event,detail) VALUES (?,?,?,?)', (user_id, now(), 'paper_order', identifier))
            return dict(db.execute('SELECT * FROM orders WHERE id=?', (identifier,)).fetchone())

    def _capacity(self, db, user_id, identifier, side, quantity, price, exclude=''):
        if side == 'BUY':
            cash_row = db.execute('SELECT cash FROM account WHERE user_id=?', (user_id,)).fetchone()
            cash = cash_row[0] if cash_row else 0
            reserved = db.execute("SELECT COALESCE(SUM(quantity*limit_price),0) FROM orders WHERE user_id=? AND status='OPEN' AND side='BUY' AND id<>?", (user_id, exclude)).fetchone()[0] + self._future_margin(db, user_id)
            if price * quantity > cash - reserved:
                raise ValueError('Insufficient available paper cash. Open buy orders reserve funds.')
        else:
            row = db.execute('SELECT quantity FROM positions WHERE user_id=? AND instrument_id=?', (user_id, identifier)).fetchone()
            reserved = db.execute("SELECT COALESCE(SUM(quantity),0) FROM orders WHERE user_id=? AND instrument_id=? AND status='OPEN' AND side='SELL' AND id<>?", (user_id, identifier, exclude)).fetchone()[0]
            if quantity > (row[0] if row else 0) - reserved:
                raise ValueError('Not enough unreserved holdings. Uncovered selling is not supported.')

    def _fill(self, db, user_id, identifier, side, quantity, price):
        row = db.execute('SELECT quantity,cost FROM positions WHERE user_id=? AND instrument_id=?', (user_id, identifier)).fetchone()
        held, cost = (row['quantity'], row['cost']) if row else (0, 0)
        if side == 'BUY':
            db.execute('INSERT OR REPLACE INTO positions (user_id, instrument_id, quantity, cost) VALUES (?,?,?,?)', (user_id, identifier, held + quantity, cost + quantity * price))
            db.execute('UPDATE account SET cash=cash-? WHERE user_id=?', (quantity * price, user_id))
        else:
            basis = cost if quantity == held else int((Decimal(cost) * quantity / held).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            db.execute('UPDATE positions SET quantity=?,cost=? WHERE user_id=? AND instrument_id=?', (held - quantity, cost - basis, user_id, identifier))
            db.execute('UPDATE account SET cash=cash+?,realized=realized+? WHERE user_id=?', (quantity * price, quantity * price - basis, user_id))

    def cancel(self, user_id_or_identifier, identifier=None):
        if identifier is None:
            identifier = user_id_or_identifier
            user_id = None
        else:
            user_id = int(user_id_or_identifier)
        with self.store.connect() as db:
            if user_id is not None:
                changed = db.execute("UPDATE orders SET status='CANCELLED' WHERE id=? AND user_id=? AND status='OPEN'", (identifier, user_id)).rowcount
            else:
                changed = db.execute("UPDATE orders SET status='CANCELLED' WHERE id=? AND status='OPEN'", (identifier,)).rowcount
            if not changed:
                raise ValueError('Only an open paper order can be cancelled.')

    def match(self, quotes, owner_id=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for order in db.execute("SELECT * FROM orders WHERE status='OPEN' ORDER BY created_at").fetchall():
                if owner_id is not None and order['user_id']!=owner_id:
                    continue
                if not contract_open(self.store.instrument(order['instrument_id'])):
                    db.execute("UPDATE orders SET status='EXPIRED' WHERE id=?",(order['id'],))
                    continue
                quote = quotes.get(order['instrument_id'])
                if not quote or quote['source'] != order['source']:
                    continue
                price = paise(quote['ltp'])
                if (order['side'] == 'BUY' and price > order['limit_price']) or (order['side'] == 'SELL' and price < order['limit_price']):
                    continue
                user_id = order['user_id'] if 'user_id' in order.keys() and order['user_id'] is not None else 1
                try:
                    self._capacity(db, user_id, order['instrument_id'], order['side'], order['quantity'], price, order['id'])
                except ValueError:
                    continue
                self._fill(db, user_id, order['instrument_id'], order['side'], order['quantity'], price)
                db.execute("UPDATE orders SET status='FILLED',fill_price=?,filled_at=? WHERE id=?", (price, now(), order['id']))

    def snapshot(self, user_id_or_quotes, quotes=None):
        if quotes is None:
            quotes = user_id_or_quotes
            user_id = 1
        else:
            user_id = int(user_id_or_quotes)
        with self.store.connect() as db:
            acc_row = db.execute('SELECT * FROM account WHERE user_id=?', (user_id,)).fetchone()
            account = dict(acc_row) if acc_row else {'initial': 0, 'cash': 0, 'realized': 0}
            rows = [dict(r) for r in db.execute('SELECT * FROM positions WHERE user_id=? AND quantity>0', (user_id,))]
            account['reserved'] = db.execute("SELECT COALESCE(SUM(quantity*limit_price),0) FROM orders WHERE user_id=? AND status='OPEN' AND side='BUY'", (user_id,)).fetchone()[0]
            margin=self._future_margin(db, user_id)
            futures=[dict(r) for r in db.execute('SELECT * FROM futures_positions WHERE user_id=? AND quantity<>0', (user_id,))]
        value, unpriced = 0, False
        for row in rows:
            try:
                row['symbol'] = self.store.instrument(row['instrument_id'])['symbol']
            except ValueError:
                row['symbol'] = row['instrument_id']
            quote = quotes.get(row['instrument_id'])
            row['average_price'] = row['cost'] / row['quantity'] / 100
            row['ltp'] = quote['ltp'] if quote else None
            row['pnl'] = (paise(quote['ltp']) * row['quantity'] - row['cost']) / 100 if quote else None
            value += paise(quote['ltp']) * row['quantity'] if quote else 0
            unpriced |= quote is None
            row['kind']='CASH'
        for row in futures:
            quote=quotes.get(row['instrument_id'])
            row['kind']='FUTURE'
            row['average_price']=row['cost']/abs(row['quantity'])/100
            row['ltp']=quote['ltp'] if quote else None
            pnl=(paise(quote['ltp'])*abs(row['quantity'])-row['cost'])*(1 if row['quantity']>0 else -1) if quote else None
            row['pnl']=pnl/100 if pnl is not None else None
            value+=pnl if pnl is not None else 0
            unpriced |= quote is None
        account['reserved']+=margin
        return {**{k: account[k] / 100 for k in ('initial', 'cash', 'realized', 'reserved')},
                'available': (account['cash'] - account['reserved']) / 100,
                'equity': None if unpriced else (account['cash'] + value) / 100,
                'positions': rows+futures, 'orders': self.store.orders(user_id), 'unpriced': unpriced,
                'futures_margin':margin/100,'futures_margin_rate':float(self.FUTURES_MARGIN_RATE)}

    def _future_margin(self, db, user_id=1, exclude=''):
        costs=[r[0] for r in db.execute('SELECT cost FROM futures_positions WHERE user_id=? AND quantity<>0 AND instrument_id<>?',(user_id, exclude))]
        return sum(self._margin(cost) for cost in costs)

    def _margin(self, cost):
        return int((Decimal(cost)*self.FUTURES_MARGIN_RATE).to_integral_value(rounding='ROUND_CEILING'))

    def _future_order(self, user_id, instrument, side, quantity, order_type, request_id, quote):
        if order_type!='MARKET':
            raise ValueError('Paper futures currently support market orders only.')
        if quantity<1 or quantity>10000 or quantity%instrument['lot_size']:
            raise ValueError(f"Quantity must be a multiple of {instrument['lot_size']} and at most 10,000 units.")
        price=paise(quote['ltp'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT * FROM orders WHERE user_id=? AND request_id=?',(user_id,request_id)).fetchone()
            if existing:
                if (existing['instrument_id'],existing['side'],existing['quantity'],existing['order_type'])!=(instrument['id'],side,quantity,order_type):
                    raise ValueError('This request identifier was already used for a different order.')
                return dict(existing)
            source_key='paper_source' if user_id==1 else f'paper_source:{user_id}'
            source=db.execute('SELECT value FROM metadata WHERE key=?',(source_key,)).fetchone()
            if source and source[0]!=quote['source']:
                raise ValueError('This paper account uses another data source. Reconnect it or reset the account before switching.')
            held=db.execute('SELECT quantity,cost FROM futures_positions WHERE user_id=? AND instrument_id=?',(user_id, instrument['id'])).fetchone()
            old_qty,old_cost=(held['quantity'],held['cost']) if held else (0,0)
            signed=quantity if side=='BUY' else -quantity
            new_qty=old_qty+signed
            realized=0
            reducing=old_qty*signed<0 and quantity<=abs(old_qty)
            if old_qty*signed>=0:
                new_cost=old_cost+quantity*price
            else:
                closed=min(abs(old_qty),quantity)
                basis=old_cost if closed==abs(old_qty) else int((Decimal(old_cost)*closed/abs(old_qty)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                realized=(closed*price-basis)*(1 if old_qty>0 else -1)
                new_cost=old_cost-basis if quantity<=abs(old_qty) else abs(new_qty)*price
            cash_row=db.execute('SELECT cash FROM account WHERE user_id=?',(user_id,)).fetchone()
            cash=(cash_row[0] if cash_row else 0)+realized
            reserved=db.execute("SELECT COALESCE(SUM(quantity*limit_price),0) FROM orders WHERE user_id=? AND status='OPEN' AND side='BUY'",(user_id,)).fetchone()[0]
            required=self._future_margin(db,user_id,instrument['id'])+self._margin(new_cost)+reserved
            if not reducing and (price*quantity>500000000 or cash<required):
                raise ValueError(f'Insufficient paper margin or order exceeds ₹50,00,000 notional. This simulator reserves 20% of futures entry value; required total ₹{required/100:,.2f}.')
            db.execute('INSERT OR REPLACE INTO futures_positions (user_id, instrument_id, symbol, quantity, cost) VALUES (?,?,?,?,?)',(user_id,instrument['id'],instrument['symbol'],new_qty,new_cost))
            db.execute('UPDATE account SET cash=cash+?,realized=realized+? WHERE user_id=?',(realized,realized,user_id))
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(source_key,quote['source']))
            identifier='P-'+uuid4().hex[:12].upper()
            db.execute('INSERT INTO orders (id, user_id, request_id, instrument_id, side, quantity, order_type, limit_price, fill_price, status, created_at, filled_at, source, symbol) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(identifier,user_id,request_id,instrument['id'],side,quantity,order_type,None,price,'FILLED',now(),now(),quote['source'],instrument['symbol']))
            db.execute('INSERT INTO audit(user_id,created_at,event,detail) VALUES (?,?,?,?)',(user_id,now(),'paper_futures_order',identifier))
            return dict(db.execute('SELECT * FROM orders WHERE id=?',(identifier,)).fetchone())
