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
    FUTURES_MARGIN_RATE = Decimal('0.20')

    def __init__(self, store):
        self.store = store

    def submit(self, instrument, side, quantity, order_type, price, request_id, quote):
        if not contract_open(instrument):
            raise ValueError('This contract has expired or its expiry is unknown. Choose an active contract.')
        if instrument['kind']=='FUTURE':
            return self._future_order(instrument,side,quantity,order_type,request_id,quote)
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
            existing = db.execute('SELECT * FROM orders WHERE request_id=?', (request_id,)).fetchone()
            if existing:
                if tuple(existing[k] for k in ('instrument_id', 'side', 'quantity', 'order_type', 'limit_price')) != requested:
                    raise ValueError('This request identifier was already used for a different order.')
                return dict(existing)
            source = db.execute("SELECT value FROM metadata WHERE key='paper_source'").fetchone()
            if source and source[0] != quote['source']:
                raise ValueError('This paper account uses another data source. Reconnect it or reset the account before switching.')
            reserve = current if fill else limit
            if reserve * quantity > 50000000:
                raise ValueError('Maximum paper order value is ₹5,00,000.')
            self._capacity(db, instrument['id'], side, quantity, reserve)
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('paper_source',?)", (quote['source'],))
            identifier = 'P-' + uuid4().hex[:12].upper()
            db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                identifier, request_id, instrument['id'], side, quantity, order_type, limit,
                current if fill else None, 'FILLED' if fill else 'OPEN', now(), now() if fill else None,
                quote['source'], instrument['symbol']))
            if fill:
                self._fill(db, instrument['id'], side, quantity, current)
            db.execute('INSERT INTO audit(created_at,event,detail) VALUES (?,?,?)', (now(), 'paper_order', identifier))
            return dict(db.execute('SELECT * FROM orders WHERE id=?', (identifier,)).fetchone())

    def _capacity(self, db, identifier, side, quantity, price, exclude=''):
        if side == 'BUY':
            cash = db.execute('SELECT cash FROM account WHERE id=1').fetchone()[0]
            reserved = db.execute("SELECT COALESCE(SUM(quantity*limit_price),0) FROM orders WHERE status='OPEN' AND side='BUY' AND id<>?", (exclude,)).fetchone()[0] + self._future_margin(db)
            if price * quantity > cash - reserved:
                raise ValueError('Insufficient available paper cash. Open buy orders reserve funds.')
        else:
            row = db.execute('SELECT quantity FROM positions WHERE instrument_id=?', (identifier,)).fetchone()
            reserved = db.execute("SELECT COALESCE(SUM(quantity),0) FROM orders WHERE instrument_id=? AND status='OPEN' AND side='SELL' AND id<>?", (identifier, exclude)).fetchone()[0]
            if quantity > (row[0] if row else 0) - reserved:
                raise ValueError('Not enough unreserved holdings. Uncovered selling is not supported.')

    def _fill(self, db, identifier, side, quantity, price):
        row = db.execute('SELECT quantity,cost FROM positions WHERE instrument_id=?', (identifier,)).fetchone()
        held, cost = (row['quantity'], row['cost']) if row else (0, 0)
        if side == 'BUY':
            db.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?)', (identifier, held + quantity, cost + quantity * price))
            db.execute('UPDATE account SET cash=cash-? WHERE id=1', (quantity * price,))
        else:
            basis = cost if quantity == held else int((Decimal(cost) * quantity / held).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            db.execute('UPDATE positions SET quantity=?,cost=? WHERE instrument_id=?', (held - quantity, cost - basis, identifier))
            db.execute('UPDATE account SET cash=cash+?,realized=realized+? WHERE id=1', (quantity * price, quantity * price - basis))

    def cancel(self, identifier):
        with self.store.connect() as db:
            changed = db.execute("UPDATE orders SET status='CANCELLED' WHERE id=? AND status='OPEN'", (identifier,)).rowcount
            if not changed:
                raise ValueError('Only an open paper order can be cancelled.')

    def match(self, quotes):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for order in db.execute("SELECT * FROM orders WHERE status='OPEN' ORDER BY created_at").fetchall():
                if not contract_open(self.store.instrument(order['instrument_id'])):
                    db.execute("UPDATE orders SET status='EXPIRED' WHERE id=?",(order['id'],))
                    continue
                quote = quotes.get(order['instrument_id'])
                if not quote or quote['source'] != order['source']:
                    continue
                price = paise(quote['ltp'])
                if (order['side'] == 'BUY' and price > order['limit_price']) or (order['side'] == 'SELL' and price < order['limit_price']):
                    continue
                try:
                    self._capacity(db, order['instrument_id'], order['side'], order['quantity'], price, order['id'])
                except ValueError:
                    continue
                self._fill(db, order['instrument_id'], order['side'], order['quantity'], price)
                db.execute("UPDATE orders SET status='FILLED',fill_price=?,filled_at=? WHERE id=?", (price, now(), order['id']))

    def snapshot(self, quotes):
        with self.store.connect() as db:
            account = dict(db.execute('SELECT * FROM account WHERE id=1').fetchone())
            rows = [dict(r) for r in db.execute('SELECT * FROM positions WHERE quantity>0')]
            account['reserved'] = db.execute("SELECT COALESCE(SUM(quantity*limit_price),0) FROM orders WHERE status='OPEN' AND side='BUY'").fetchone()[0]
            margin=self._future_margin(db)
            futures=[dict(r) for r in db.execute('SELECT * FROM futures_positions WHERE quantity<>0')]
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
                'positions': rows+futures, 'orders': self.store.orders(), 'unpriced': unpriced,
                'futures_margin':margin/100,'futures_margin_rate':float(self.FUTURES_MARGIN_RATE)}

    def _future_margin(self, db, exclude=''):
        costs=[r[0] for r in db.execute('SELECT cost FROM futures_positions WHERE quantity<>0 AND instrument_id<>?',(exclude,))]
        return sum(self._margin(cost) for cost in costs)

    def _margin(self, cost):
        return int((Decimal(cost)*self.FUTURES_MARGIN_RATE).to_integral_value(rounding='ROUND_CEILING'))

    def _future_order(self, instrument, side, quantity, order_type, request_id, quote):
        if order_type!='MARKET':
            raise ValueError('Paper futures currently support market orders only.')
        if quantity<1 or quantity>10000 or quantity%instrument['lot_size']:
            raise ValueError(f"Quantity must be a multiple of {instrument['lot_size']} and at most 10,000 units.")
        price=paise(quote['ltp'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT * FROM orders WHERE request_id=?',(request_id,)).fetchone()
            if existing:
                if (existing['instrument_id'],existing['side'],existing['quantity'],existing['order_type'])!=(instrument['id'],side,quantity,order_type):
                    raise ValueError('This request identifier was already used for a different order.')
                return dict(existing)
            source=db.execute("SELECT value FROM metadata WHERE key='paper_source'").fetchone()
            if source and source[0]!=quote['source']:
                raise ValueError('This paper account uses another data source. Reconnect it or reset the account before switching.')
            held=db.execute('SELECT quantity,cost FROM futures_positions WHERE instrument_id=?',(instrument['id'],)).fetchone()
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
            cash=db.execute('SELECT cash FROM account WHERE id=1').fetchone()[0]+realized
            reserved=db.execute("SELECT COALESCE(SUM(quantity*limit_price),0) FROM orders WHERE status='OPEN' AND side='BUY'").fetchone()[0]
            required=self._future_margin(db,instrument['id'])+self._margin(new_cost)+reserved
            if not reducing and (price*quantity>500000000 or cash<required):
                raise ValueError(f'Insufficient paper margin or order exceeds ₹50,00,000 notional. This simulator reserves 20% of futures entry value; required total ₹{required/100:,.2f}.')
            db.execute('INSERT OR REPLACE INTO futures_positions VALUES (?,?,?,?)',(instrument['id'],instrument['symbol'],new_qty,new_cost))
            db.execute('UPDATE account SET cash=cash+?,realized=realized+? WHERE id=1',(realized,realized))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('paper_source',?)",(quote['source'],))
            identifier='P-'+uuid4().hex[:12].upper()
            db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(identifier,request_id,instrument['id'],side,quantity,order_type,None,price,'FILLED',now(),now(),quote['source'],instrument['symbol']))
            db.execute('INSERT INTO audit(created_at,event,detail) VALUES (?,?,?)',(now(),'paper_futures_order',identifier))
            return dict(db.execute('SELECT * FROM orders WHERE id=?',(identifier,)).fetchone())
