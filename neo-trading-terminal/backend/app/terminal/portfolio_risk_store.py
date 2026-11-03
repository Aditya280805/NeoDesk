"""Owner-scoped immutable risk persistence; no broker or model access."""
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import UUID
from .portfolio_risk_contracts import RiskPolicy, RiskPolicyUpdate, RiskReport

class PolicyConflictError(Exception):
    """The policy changed; reload before updating."""

class ReportConflictError(Exception):
    """A report identifier already exists with different owner or content."""

class RiskStoreBusyError(Exception):
    """Risk storage is busy; retry later."""

def _owner(user_id):
    if type(user_id) is not int or user_id <= 0:
        raise ValueError('A positive authenticated user ID is required')

def _json(value):
    return json.dumps(value.model_dump(mode='json'),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def _busy(exc):
    if (getattr(exc,'sqlite_errorcode',0) & 255) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
        raise RiskStoreBusyError('Risk storage is busy; retry later') from None
    raise exc

class PortfolioRiskStore:
    def __init__(self,store):
        self.store=store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS portfolio_risk_policy_revisions (
                    user_id INTEGER NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
                    payload TEXT NOT NULL, PRIMARY KEY(user_id,revision));
                CREATE TABLE IF NOT EXISTS portfolio_risk_policy_heads (
                    user_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>0));
                CREATE TABLE IF NOT EXISTS portfolio_risk_reports (
                    report_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS portfolio_risk_reports_owner ON portfolio_risk_reports(user_id,created_at);
                CREATE TRIGGER IF NOT EXISTS portfolio_risk_reports_immutable BEFORE UPDATE ON portfolio_risk_reports
                    BEGIN SELECT RAISE(ABORT,'immutable risk report'); END;
                CREATE TRIGGER IF NOT EXISTS portfolio_risk_revisions_immutable BEFORE UPDATE ON portfolio_risk_policy_revisions
                    BEGIN SELECT RAISE(ABORT,'immutable risk revision'); END;
            ''')

    def get_policy(self,user_id:int)->RiskPolicy:
        _owner(user_id)
        try:
            with self.store.connect() as db:
                db.execute('PRAGMA busy_timeout=1000')
                row=db.execute('SELECT r.payload FROM portfolio_risk_policy_revisions r JOIN portfolio_risk_policy_heads h ON r.user_id=h.user_id AND r.revision=h.revision WHERE h.user_id=?',(user_id,)).fetchone()
            return RiskPolicy.model_validate_json(row[0]) if row else RiskPolicy(revision=0)
        except sqlite3.OperationalError as exc: _busy(exc)

    def update_policy(self,user_id:int,update:RiskPolicyUpdate)->RiskPolicy:
        _owner(user_id)
        try:
            with self.store.connect() as db:
                db.execute('PRAGMA busy_timeout=1000')
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT revision FROM portfolio_risk_policy_heads WHERE user_id=?',(user_id,)).fetchone()
                current=row[0] if row else 0
                if current!=update.expected_revision:
                    raise PolicyConflictError('Risk policy changed; reload before updating')
                policy=RiskPolicy(**update.policy.model_dump(),revision=current+1)
                db.execute('INSERT INTO portfolio_risk_policy_revisions VALUES (?,?,?)',(user_id,policy.revision,_json(policy)))
                if row:
                    result=db.execute('UPDATE portfolio_risk_policy_heads SET revision=? WHERE user_id=? AND revision=?',(policy.revision,user_id,current))
                    if result.rowcount!=1: raise PolicyConflictError('Risk policy changed; reload before updating')
                else: db.execute('INSERT INTO portfolio_risk_policy_heads VALUES (?,?)',(user_id,policy.revision))
            return policy
        except sqlite3.OperationalError as exc: _busy(exc)

    def save_report(self,db,user_id:int,report:RiskReport)->None:
        _owner(user_id)
        if not db.in_transaction:
            raise ValueError('save_report requires an active caller transaction')
        payload=_json(report)
        try:
            db.execute('PRAGMA busy_timeout=1000')
            db.execute('INSERT INTO portfolio_risk_reports VALUES (?,?,?,?) ON CONFLICT(report_id) DO NOTHING',(str(report.report_id),user_id,datetime.now(UTC).isoformat(),payload))
            row=db.execute('SELECT user_id,payload FROM portfolio_risk_reports WHERE report_id=?',(str(report.report_id),)).fetchone()
            if row[0]!=user_id or row[1]!=payload: raise ReportConflictError('Report identifier conflicts with saved report')
        except sqlite3.OperationalError as exc: _busy(exc)

    def get_report(self,user_id:int,report_id:UUID)->RiskReport|None:
        _owner(user_id)
        with self.store.connect() as db:
            row=db.execute('SELECT payload FROM portfolio_risk_reports WHERE user_id=? AND report_id=?',(user_id,str(report_id))).fetchone()
        return RiskReport.model_validate_json(row[0]) if row else None

    def prune_reports(self,older_than_days:int,*,apply:bool=False)->list[str]:
        if type(older_than_days) is not int or older_than_days<1: raise ValueError('Age must be a positive integer in days')
        cutoff=(datetime.now(UTC)-timedelta(days=older_than_days)).isoformat()
        with self.store.connect() as db:
            db.execute('PRAGMA busy_timeout=1000')
            db.execute('BEGIN IMMEDIATE')
            # Traverse all nested JSON values conservatively: future report reference
            # locations can be introduced without weakening retention safety.
            references=set()
            def collect(value):
                if isinstance(value,str): references.add(value)
                elif isinstance(value,list):
                    for item in value: collect(item)
                elif isinstance(value,dict):
                    for key,item in value.items():
                        references.add(key)
                        collect(item)
            for table,column in (('option_chat_turns','evidence'),('option_chat_turns','answer'),('option_agent_runs','detail')):
                if db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone():
                    for row in db.execute(f'SELECT {column} FROM {table}'):
                        if row[0] is None: continue
                        try: collect(json.loads(row[0]))
                        except (TypeError,ValueError):
                            if column == 'answer':
                                # Production answers are free-form prose. Legacy JSON
                                # answers are scanned above when they decode.
                                continue
                            # Unknown legacy/corrupt reference storage must never cause deletion.
                            return []
            candidates=[row[0] for row in db.execute('SELECT report_id FROM portfolio_risk_reports WHERE created_at<? ORDER BY report_id',(cutoff,)) if row[0] not in references]
            if apply: db.executemany('DELETE FROM portfolio_risk_reports WHERE report_id=?',[(item,) for item in candidates])
            return candidates
