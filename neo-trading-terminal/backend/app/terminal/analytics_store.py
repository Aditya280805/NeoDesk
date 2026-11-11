"""Additive owner-scoped immutable analytics evidence storage."""
import json
import sqlite3
from pathlib import Path


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

    def connect(self):
        return sqlite3.connect(self.path,timeout=10)

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
