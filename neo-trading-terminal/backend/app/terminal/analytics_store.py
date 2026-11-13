"""Additive owner-scoped immutable analytics evidence storage."""
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from contextlib import nullcontext
import time


class AnalyticsStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS analytics_evidence (
                user_id INTEGER NOT NULL, evidence_id TEXT NOT NULL, captured_at TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(user_id,evidence_id));
              CREATE TABLE IF NOT EXISTS analytics_source_revisions (
                source TEXT NOT NULL, report_date TEXT NOT NULL, checksum TEXT NOT NULL,
                retrieved_at TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(source,report_date,checksum));
              CREATE TABLE IF NOT EXISTS analytics_continuations (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at REAL NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path,timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def capture(self, user_id, evidence_id, captured_at, payload):
        if not isinstance(user_id,int) or isinstance(user_id,bool) or user_id <= 0:
            raise ValueError('Authenticated owner required')
        encoded = json.dumps(payload,allow_nan=False,sort_keys=True)
        with self.connect() as db:
            existing = db.execute('SELECT payload FROM analytics_evidence WHERE user_id=? AND evidence_id=?',(user_id,evidence_id)).fetchone()
            if existing:
                if existing[0] != encoded:
                    raise ValueError('Immutable evidence conflict')
                return
            db.execute('INSERT INTO analytics_evidence VALUES (?,?,?,?)',(user_id,evidence_id,captured_at,encoded))

    def read(self,user_id,evidence_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM analytics_evidence WHERE user_id=? AND evidence_id=?',(user_id,evidence_id)).fetchone()
        return json.loads(row[0]) if row else None

    def capture_batch(self,user_id,evidence,*,validate=None,publication_guard=None,deadline=None):
        """Publish a complete capture atomically; conflicts roll the batch back."""
        if type(user_id) is not int or user_id<=0:
            raise ValueError('Authenticated owner required')
        with publication_guard() if publication_guard is not None else nullcontext():
            with self.connect() as db:
                if deadline is not None:
                    remaining = deadline-time.monotonic()
                    if remaining<=0:
                        raise TimeoutError('Capture publication deadline exhausted')
                    db.execute('PRAGMA busy_timeout = %d' % max(1,min(10000,int(remaining*1000))))
                if validate is not None:
                    validate()
                for item in evidence:
                    payload = item.model_dump(mode='json')
                    identity = str(item.evidence_id)
                    encoded = json.dumps(payload,allow_nan=False,sort_keys=True)
                    existing = db.execute('SELECT payload FROM analytics_evidence WHERE user_id=? AND evidence_id=?',(user_id,identity)).fetchone()
                    if existing:
                        if existing[0]!=encoded:
                            raise ValueError('Immutable evidence conflict')
                    else:
                        db.execute('INSERT INTO analytics_evidence VALUES (?,?,?,?)',(user_id,identity,item.retrieved_at.isoformat(),encoded))
                if validate is not None:
                    validate()
