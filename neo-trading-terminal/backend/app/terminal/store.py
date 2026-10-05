"""Single-user persistent storage. Money is stored in integer paise."""
import json
import sqlite3
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
