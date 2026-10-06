"""Single-user persistent storage. Money is stored in integer paise."""
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
                CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY, initial INTEGER, cash INTEGER, realized INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS positions (instrument_id TEXT PRIMARY KEY, quantity INTEGER, cost INTEGER);
                CREATE TABLE IF NOT EXISTS futures_positions (instrument_id TEXT PRIMARY KEY, symbol TEXT, quantity INTEGER, cost INTEGER);
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE, instrument_id TEXT,
                    side TEXT, quantity INTEGER, order_type TEXT, limit_price INTEGER,
                    fill_price INTEGER, status TEXT, created_at TEXT, filled_at TEXT,
                    source TEXT, symbol TEXT);
                CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, created_at TEXT, event TEXT, detail TEXT);
                CREATE TABLE IF NOT EXISTS watchlist (instrument_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS strategies (
                    id TEXT PRIMARY KEY, name TEXT, strategy_type TEXT, instrument_id TEXT,
                    token TEXT, params TEXT NOT NULL, mode TEXT, status TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, cash REAL NOT NULL,
                    held INTEGER DEFAULT 0, realized_pnl REAL DEFAULT 0.0, total_trades INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS strategies_status ON strategies(status);
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY, strategy_id TEXT, instrument_id TEXT,
                    action TEXT, price REAL, indicator_type TEXT, metadata TEXT,
                    timestamp REAL NOT NULL, order_id TEXT);
                CREATE INDEX IF NOT EXISTS signals_strategy ON signals(strategy_id, timestamp);
            ''')
            db.execute("INSERT OR IGNORE INTO account(id,initial,cash) VALUES (1,?,?)", (balance * 100, balance * 100))
            if not db.execute("SELECT 1 FROM metadata WHERE key='catalogue_v2'").fetchone():
                for row in db.execute('SELECT payload FROM instruments').fetchall():
                    item=normalise(json.loads(row[0]))
                    db.execute('UPDATE instruments SET kind=?,payload=? WHERE id=?', (item['kind'],json.dumps(item),item['id']))
                db.execute("INSERT INTO metadata VALUES ('catalogue_v2','1')")
            db.execute('CREATE INDEX IF NOT EXISTS instruments_lookup ON instruments(exchange,kind,underlying)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def audit(self, event, detail):
        with self.connect() as db:
            db.execute("INSERT INTO audit(created_at,event,detail) VALUES (?,?,?)", (now(), event, detail))

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
        ordering = {'symbol': 'symbol ASC', 'symbol_desc': 'symbol DESC', 'exchange': 'exchange,symbol', 'kind': 'kind,symbol'}[sort]
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

    def watchlist(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT i.payload FROM instruments i JOIN watchlist w ON i.id=w.instrument_id ORDER BY i.symbol')]

    def watch(self, identifier, add=True):
        self.instrument(identifier)
        with self.connect() as db:
            if add:
                if db.execute('SELECT COUNT(*) FROM watchlist').fetchone()[0] >= 50:
                    raise ValueError('Watchlists support up to 50 instruments.')
                db.execute('INSERT OR IGNORE INTO watchlist VALUES (?)', (identifier,))
            else:
                db.execute('DELETE FROM watchlist WHERE instrument_id=?', (identifier,))

    def orders(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT 200')]

    def save_strategy(self, strat: Dict[str, Any]):
        with self.connect() as db:
            db.execute('''
                INSERT OR REPLACE INTO strategies (
                    id, name, strategy_type, instrument_id, token, params, mode, status,
                    created_at, updated_at, cash, held, realized_pnl, total_trades
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                strat['id'],
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

    def get_strategy(self, sid: str) -> Optional[Dict[str, Any]]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM strategies WHERE id=?", (sid,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data['params'] = json.loads(data['params']) if data.get('params') else {}
            return data

    def list_strategies(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.connect() as db:
            if status:
                rows = db.execute("SELECT * FROM strategies WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM strategies ORDER BY created_at DESC").fetchall()
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

    def record_signal(self, sig) -> str:
        sig_id = str(uuid.uuid4())
        sig_dict = sig.to_dict() if hasattr(sig, 'to_dict') else sig
        with self.connect() as db:
            db.execute('''
                INSERT INTO signals (id, strategy_id, instrument_id, action, price, indicator_type, metadata, timestamp, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                sig_id,
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

    def get_signals(self, strategy_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self.connect() as db:
            if strategy_id:
                rows = db.execute(
                    "SELECT * FROM signals WHERE strategy_id=? ORDER BY timestamp DESC LIMIT ?", 
                    (strategy_id, limit)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", 
                    (limit,)
                ).fetchall()
            res = []
            for r in rows:
                item = dict(r)
                item['metadata'] = json.loads(item['metadata']) if item.get('metadata') else {}
                res.append(item)
            return res
