"""Account-scoped persistent storage. Money is stored in integer paise."""
import json
import sqlite3
import time
import uuid
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from app.terminal.catalogue import normalise


def now():
    return datetime.now(UTC).isoformat()


class Store:
    """
    Manages local SQLite database for the terminal.
    
    This class is responsible for persisting the instrument catalogue, user watchlists, 
    paper trading accounts, strategy configurations, and trading signals. It uses SQLite 
    in WAL mode for concurrent access and thread safety across the FastAPI application.
    """
    def __init__(self, path: Path, balance: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS instruments (
                    id TEXT PRIMARY KEY, symbol TEXT, name TEXT, exchange TEXT,
                    kind TEXT, underlying TEXT, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS instruments_symbol ON instruments(symbol);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE DEFAULT 1,
                    initial INTEGER, cash INTEGER, realized INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS positions (
                    user_id INTEGER DEFAULT 1, instrument_id TEXT, quantity INTEGER, cost INTEGER,
                    PRIMARY KEY (user_id, instrument_id));
                CREATE TABLE IF NOT EXISTS futures_positions (
                    user_id INTEGER DEFAULT 1, instrument_id TEXT, symbol TEXT, quantity INTEGER, cost INTEGER,
                    PRIMARY KEY (user_id, instrument_id));
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, user_id INTEGER DEFAULT 1, request_id TEXT, instrument_id TEXT,
                    side TEXT, quantity INTEGER, order_type TEXT, limit_price INTEGER,
                    fill_price INTEGER, status TEXT, created_at TEXT, filled_at TEXT,
                    source TEXT, symbol TEXT, UNIQUE(user_id,request_id));
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 1,
                    created_at TEXT, event TEXT, detail TEXT);
                CREATE TABLE IF NOT EXISTS watchlist (
                    user_id INTEGER DEFAULT 1, instrument_id TEXT,
                    PRIMARY KEY (user_id, instrument_id));
                CREATE TABLE IF NOT EXISTS strategies (
                    id TEXT PRIMARY KEY, user_id INTEGER DEFAULT 1, name TEXT, strategy_type TEXT, instrument_id TEXT,
                    token TEXT, params TEXT NOT NULL, mode TEXT, status TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, cash REAL NOT NULL,
                    held INTEGER DEFAULT 0, realized_pnl REAL DEFAULT 0.0, total_trades INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS strategies_status ON strategies(status);
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY, user_id INTEGER DEFAULT 1, strategy_id TEXT, instrument_id TEXT,
                    action TEXT, price REAL, indicator_type TEXT, metadata TEXT,
                    timestamp REAL NOT NULL, order_id TEXT);
                CREATE INDEX IF NOT EXISTS signals_strategy ON signals(strategy_id, timestamp);
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS users_email ON users(email);
                CREATE TABLE IF NOT EXISTS broker_identities (
                    broker TEXT NOT NULL, account_hash TEXT NOT NULL, user_id INTEGER NOT NULL,
                    PRIMARY KEY (broker, account_hash));
                CREATE TABLE IF NOT EXISTS live_requests (
                    user_id INTEGER NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL,
                    result TEXT, PRIMARY KEY (user_id, request_id));
            ''')

            # Multi-user schema migration for existing databases
            if not db.execute("SELECT 1 FROM metadata WHERE key='multi_user_v1'").fetchone():
                for table in ('account', 'positions', 'futures_positions', 'orders', 'watchlist', 'strategies', 'signals', 'audit'):
                    try:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 1')
                    except sqlite3.OperationalError:
                        pass

                # If existing tables had single-column PK on instrument_id, migrate to compound PK
                for tbl, cols, defn in [
                    ('positions', 'user_id, instrument_id, quantity, cost', 'user_id INTEGER DEFAULT 1, instrument_id TEXT, quantity INTEGER, cost INTEGER, PRIMARY KEY (user_id, instrument_id)'),
                    ('futures_positions', 'user_id, instrument_id, symbol, quantity, cost', 'user_id INTEGER DEFAULT 1, instrument_id TEXT, symbol TEXT, quantity INTEGER, cost INTEGER, PRIMARY KEY (user_id, instrument_id)'),
                    ('watchlist', 'user_id, instrument_id', 'user_id INTEGER DEFAULT 1, instrument_id TEXT, PRIMARY KEY (user_id, instrument_id)')
                ]:
                    pk_cols = [r[1] for r in db.execute(f"PRAGMA table_info({tbl})").fetchall() if r[5] > 0]
                    if pk_cols == ['instrument_id']:
                        db.execute(f"CREATE TABLE {tbl}_v2 ({defn})")
                        db.execute(f"INSERT OR IGNORE INTO {tbl}_v2 SELECT {cols} FROM {tbl}")
                        db.execute(f"DROP TABLE {tbl}")
                        db.execute(f"ALTER TABLE {tbl}_v2 RENAME TO {tbl}")

                db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_account_user ON account(user_id)')
                db.execute('CREATE UNIQUE INDEX IF NOT EXISTS positions_user_inst ON positions(user_id, instrument_id)')
                db.execute('CREATE UNIQUE INDEX IF NOT EXISTS futures_user_inst ON futures_positions(user_id, instrument_id)')
                db.execute('CREATE UNIQUE INDEX IF NOT EXISTS watchlist_user_inst ON watchlist(user_id, instrument_id)')

                db.execute('CREATE INDEX IF NOT EXISTS idx_positions_user ON positions(user_id)')
                db.execute('CREATE INDEX IF NOT EXISTS idx_futures_user ON futures_positions(user_id)')
                db.execute('CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)')
                db.execute('CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)')
                db.execute('CREATE INDEX IF NOT EXISTS idx_strategies_user ON strategies(user_id)')
                db.execute('CREATE INDEX IF NOT EXISTS idx_signals_user ON signals(user_id)')

                db.execute("INSERT OR REPLACE INTO metadata VALUES ('multi_user_v1', '1')")

            # Replace the old global retry constraint without losing order history.
            global_retry_key=any(
                r['unique'] and [c['name'] for c in db.execute(f"PRAGMA index_info('{r['name']}')")]==['request_id']
                for r in db.execute('PRAGMA index_list(orders)').fetchall())
            if global_retry_key:
                db.execute('''CREATE TABLE orders_scoped (
                    id TEXT PRIMARY KEY, user_id INTEGER DEFAULT 1, request_id TEXT, instrument_id TEXT,
                    side TEXT, quantity INTEGER, order_type TEXT, limit_price INTEGER,
                    fill_price INTEGER, status TEXT, created_at TEXT, filled_at TEXT,
                    source TEXT, symbol TEXT, UNIQUE(user_id,request_id))''')
                columns='id,user_id,request_id,instrument_id,side,quantity,order_type,limit_price,fill_price,status,created_at,filled_at,source,symbol'
                db.execute(f'INSERT INTO orders_scoped ({columns}) SELECT {columns} FROM orders')
                db.execute('DROP TABLE orders')
                db.execute('ALTER TABLE orders_scoped RENAME TO orders')
                db.execute('CREATE INDEX idx_orders_user ON orders(user_id)')

            db.execute("INSERT OR IGNORE INTO account(id, user_id, initial, cash) VALUES (1, 1, ?, ?)", (balance * 100, balance * 100))
            if not db.execute("SELECT 1 FROM metadata WHERE key='catalogue_v2'").fetchone():
                for row in db.execute('SELECT payload FROM instruments').fetchall():
                    item=normalise(json.loads(row[0]))
                    db.execute('UPDATE instruments SET kind=?,payload=? WHERE id=?', (item['kind'],json.dumps(item),item['id']))
                db.execute("INSERT INTO metadata VALUES ('catalogue_v2','1')")
            db.execute('CREATE INDEX IF NOT EXISTS instruments_lookup ON instruments(exchange,kind,underlying)')
            if not db.execute("SELECT 1 FROM metadata WHERE key='cash_classification_v3'").fetchone():
                for row in db.execute("SELECT payload FROM instruments WHERE kind='EQUITY' AND exchange IN ('nse_cm','bse_cm')").fetchall():
                    old=json.loads(row[0])
                    item=normalise(old)
                    if item['kind']!=old['kind']:
                        db.execute('UPDATE instruments SET kind=?,payload=? WHERE id=?',(item['kind'],json.dumps(item),item['id']))
                db.execute("INSERT INTO metadata VALUES ('cash_classification_v3','1')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def init_user_account(self, user_id: int, balance: int):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO account(id, user_id, initial, cash) VALUES (NULL, ?, ?, ?)',
                       (user_id, balance * 100, balance * 100))

    def audit(self, user_id: int | str, event: str = "", detail: str = ""):
        if isinstance(user_id, str):
            event, detail, user_id = user_id, event, 1
        with self.connect() as db:
            db.execute("INSERT INTO audit(user_id,created_at,event,detail) VALUES (?,?,?,?)", (user_id, now(), event, detail))

    def instrument(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM instruments WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Instrument not found. Sync the instrument catalogue in Connections.")
        return json.loads(row[0])

    def search(self, query='', exchange='', kind='', sort='symbol', offset=0, limit=40, scope=''):
        clause, args = [], []
        if query:
            clause.append("(symbol LIKE ? OR name LIKE ? OR underlying LIKE ?)")
            args += [f'%{query}%'] * 3
        if exchange:
            clause.append("exchange=?")
            args.append(exchange)
        if kind:
            clause.append("kind=?")
            args.append(kind)
        if scope == 'stocks':
            clause.append("exchange IN ('nse_cm','bse_cm') AND kind IN ('EQUITY','ETF')")
        where = ' WHERE ' + ' AND '.join(clause) if clause else ''
        ordering = {'name':'name COLLATE NOCASE,symbol','name_desc':'name COLLATE NOCASE DESC,symbol',
                    'symbol': 'symbol ASC', 'symbol_desc': 'symbol DESC', 'exchange': 'exchange,symbol', 'kind': 'kind,symbol'}[sort]
        with self.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM instruments' + where, args).fetchone()[0]
            rows = db.execute('SELECT payload FROM instruments' + where + f' ORDER BY {ordering} LIMIT ? OFFSET ?', args + [limit, offset]).fetchall()
        return {'total': count, 'items': [json.loads(r[0]) for r in rows]}

    def save_catalogue(self, rows, segments):
        rows=[normalise(i) for i in rows]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Atomic per full refresh: a failed download never removes the existing catalogue.
            for segment in segments:
                # Retain metadata for held/ordered contracts that leave the current master.
                db.execute("DELETE FROM instruments WHERE exchange=? AND id NOT IN (SELECT instrument_id FROM positions WHERE quantity<>0) AND id NOT IN (SELECT instrument_id FROM futures_positions WHERE quantity<>0) AND id NOT IN (SELECT instrument_id FROM orders WHERE status='OPEN')", (segment,))
            db.executemany('INSERT OR REPLACE INTO instruments VALUES (?,?,?,?,?,?,?)', [
                (i['id'], i['symbol'], i['name'], i['exchange'], i['kind'], i['underlying'], json.dumps(i)) for i in rows
            ])
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('catalogue_updated_at', now()))

    def metadata(self):
        with self.connect() as db:
            counts = [dict(r) for r in db.execute('SELECT exchange,kind,COUNT(*) AS count FROM instruments GROUP BY exchange,kind')]
            stamp = db.execute("SELECT value FROM metadata WHERE key='catalogue_updated_at'").fetchone()
        return {'counts': counts, 'updated_at': stamp[0] if stamp else None, 'total': sum(r['count'] for r in counts)}

    def watchlist(self, user_id: int = 1):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT i.payload FROM instruments i JOIN watchlist w ON i.id=w.instrument_id WHERE w.user_id=? ORDER BY i.symbol', (user_id,))]

    def watch(self, user_id: int | str, identifier: Optional[str] = None, add: bool = True):
        if identifier is None or isinstance(identifier, bool):
            add = identifier if isinstance(identifier, bool) else add
            identifier = str(user_id)
            user_id = 1
        else:
            user_id = int(user_id)

        self.instrument(identifier)
        with self.connect() as db:
            if add:
                if db.execute('SELECT COUNT(*) FROM watchlist WHERE user_id=?', (user_id,)).fetchone()[0] >= 50:
                    raise ValueError('Watchlists support up to 50 instruments.')
                db.execute('INSERT OR IGNORE INTO watchlist (user_id, instrument_id) VALUES (?, ?)', (user_id, identifier))
            else:
                db.execute('DELETE FROM watchlist WHERE user_id=? AND instrument_id=?', (user_id, identifier))

    def orders(self, user_id: Optional[int] = 1):
        with self.connect() as db:
            if user_id is None:
                return [dict(r) for r in db.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT 200')]
            return [dict(r) for r in db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 200', (user_id,))]

    def save_strategy(self, *args, **kwargs):
        strat = kwargs.get('strat')
        user_id = kwargs.get('user_id')
        if args:
            if len(args) == 1:
                if isinstance(args[0], dict):
                    strat = args[0]
                else:
                    user_id = args[0]
            elif len(args) >= 2:
                if isinstance(args[0], int):
                    user_id, strat = args[0], args[1]
                else:
                    strat, user_id = args[0], args[1]
        if user_id is None and isinstance(strat, dict):
            user_id = strat.get('user_id', 1)
        elif user_id is None:
            user_id = 1


        with self.connect() as db:
            db.execute('''
                INSERT OR REPLACE INTO strategies (
                    id, user_id, name, strategy_type, instrument_id, token, params, mode, status,
                    created_at, updated_at, cash, held, realized_pnl, total_trades
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                strat['id'],
                user_id,
                strat.get('name', strat['id']),
                strat.get('strategy_type', 'SMA_CROSSOVER'),
                strat['instrument_id'],
                strat.get('token', ''),
                json.dumps(strat.get('params', {})),
                strat.get('mode', 'paper'),
                strat.get('status', 'RUNNING'),
                strat.get('created_at', time.time()),
                strat.get('updated_at', time.time()),
                float(strat.get('cash', 0.0)),
                int(strat.get('held', 0)),
                float(strat.get('realized_pnl', 0.0)),
                int(strat.get('total_trades', 0))
            ))

    def get_strategy(self, sid_or_user: Any, user_or_sid: Any = None) -> Optional[Dict[str, Any]]:
        if isinstance(sid_or_user, int) and isinstance(user_or_sid, str):
            user_id = sid_or_user
            sid = user_or_sid
        elif isinstance(sid_or_user, str) and isinstance(user_or_sid, int):
            sid = sid_or_user
            user_id = user_or_sid
        elif isinstance(sid_or_user, str) and user_or_sid is None:
            sid = sid_or_user
            user_id = None
        else:
            sid = str(sid_or_user)
            user_id = int(user_or_sid) if user_or_sid is not None else None

        with self.connect() as db:
            if user_id is not None:
                row = db.execute("SELECT * FROM strategies WHERE id=? AND user_id=?", (sid, user_id)).fetchone()
            else:
                row = db.execute("SELECT * FROM strategies WHERE id=?", (sid,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data['params'] = json.loads(data['params']) if data.get('params') else {}
            return data

    def list_strategies(self, user_id: Optional[int | str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if isinstance(user_id, str):
            status = user_id
            user_id = None
        with self.connect() as db:
            query = "SELECT * FROM strategies"
            clauses = []
            params: List[Any] = []
            if user_id is not None:
                clauses.append("user_id=?")
                params.append(user_id)
            if status is not None:
                clauses.append("status=?")
                params.append(status)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY created_at DESC"
            rows = db.execute(query, params).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item['params'] = json.loads(item['params']) if item.get('params') else {}
                result.append(item)
            return result

    def update_strategy_state(self, sid: str, cash: float, held: int, realized_pnl: Optional[float] = None, total_trades: Optional[int] = None, status: Optional[str] = None):
        with self.connect() as db:
            updates = ["updated_at = ?", "cash = ?", "held = ?"]
            args: List[Any] = [time.time(), cash, held]
            if realized_pnl is not None:
                updates.append("realized_pnl = ?")
                args.append(realized_pnl)
            if total_trades is not None:
                updates.append("total_trades = ?")
                args.append(total_trades)
            if status is not None:
                updates.append("status = ?")
                args.append(status)
            args.append(sid)
            db.execute(f"UPDATE strategies SET {', '.join(updates)} WHERE id=?", args)

    def record_signal(self, sig_or_user: Any, user_or_sig: Any = None) -> str:
        if isinstance(sig_or_user, int):
            user_id = sig_or_user
            sig = user_or_sig
        elif isinstance(user_or_sig, int):
            sig = sig_or_user
            user_id = user_or_sig
        else:
            sig = sig_or_user
            user_id = getattr(sig, 'user_id', None) or (sig.get('user_id') if isinstance(sig, dict) else 1) or 1

        sig_id = str(uuid.uuid4())
        sig_dict = sig.to_dict() if hasattr(sig, 'to_dict') else sig
        with self.connect() as db:
            db.execute('''
                INSERT INTO signals (id, user_id, strategy_id, instrument_id, action, price, indicator_type, metadata, timestamp, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                sig_id,
                user_id,
                sig_dict['strategy_id'],
                sig_dict['instrument_id'],
                sig_dict['action'],
                sig_dict['price'],
                sig_dict['indicator_type'],
                json.dumps(sig_dict.get('metadata', {})),
                sig_dict['timestamp'],
                sig_dict.get('order_id')
            ))
        return sig_id

    def get_signals(self, user_id: Optional[int | str] = None, strategy_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if isinstance(user_id, str):
            strategy_id = user_id
            user_id = None
        with self.connect() as db:
            query = "SELECT * FROM signals"
            clauses = []
            params: List[Any] = []
            if user_id is not None:
                clauses.append("user_id=?")
                params.append(user_id)
            if strategy_id is not None:
                clauses.append("strategy_id=?")
                params.append(strategy_id)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = db.execute(query, params).fetchall()
            res = []
            for r in rows:
                item = dict(r)
                item['metadata'] = json.loads(item['metadata']) if item.get('metadata') else {}
                res.append(item)
            return res

    def broker_user(self, account_hash: str, display_name: str, balance: int) -> dict:
        """Resolve an identity only AFTER successful broker authentication."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT user_id FROM broker_identities WHERE broker='kotak' AND account_hash=?", (account_hash,)).fetchone()
            if row:
                user_id = row[0]
            else:
                # Broker-only identities cannot authenticate through email/password.
                # Keep the pre-existing anonymous/local account (user 1) separate.
                next_id = max(2, db.execute('SELECT COALESCE(MAX(id),0)+1 FROM users').fetchone()[0])
                db.execute('INSERT INTO users(id,email,password_hash,display_name,created_at) VALUES (?,?,?,?,?)',
                           (next_id, f'kotak-{account_hash}@broker.invalid', '!broker-only', display_name, now()))
                user_id = next_id
                db.execute("INSERT INTO broker_identities VALUES ('kotak',?,?)", (account_hash, user_id))
                db.execute('INSERT OR IGNORE INTO account(user_id,initial,cash) VALUES (?,?,?)', (user_id,balance*100,balance*100))
        return self.get_user_by_id(user_id)

    def create_user(self, email: str, password_hash: str, display_name: str) -> dict:
        created = now()
        clean_email = email.strip().lower()
        clean_name = display_name.strip()
        with self.connect() as db:
            try:
                cur = db.execute(
                    "INSERT INTO users (email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
                    (clean_email, password_hash, clean_name, created)
                )
                user_id = cur.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError("Email already registered")
        return {
            "id": user_id,
            "email": clean_email,
            "display_name": clean_name,
            "created_at": created,
        }

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        clean_email = email.strip().lower()
        with self.connect() as db:
            row = db.execute(
                "SELECT id, email, password_hash, display_name, created_at FROM users WHERE email = ?",
                (clean_email,)
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self.connect() as db:
            row = db.execute(
                "SELECT id, email, password_hash, display_name, created_at FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
        if not row:
            return None
        return dict(row)

