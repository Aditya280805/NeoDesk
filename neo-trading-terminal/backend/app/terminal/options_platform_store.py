"""Additive SQLite owner boundaries and immutable canonical strategy artifacts."""
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import sqlite3
from uuid import UUID
from .options_market_contracts import StrategyMarketEvidence
from .options_strategy_contracts import StrategyReport, StrategyBaseline
from .options_monitoring_store import MonitoringStoreMixin

class PlatformStoreBusyError(Exception): pass
class PlatformConflictError(Exception): pass

def _owner(user_id):
    if type(user_id) is not int or user_id<=0: raise ValueError('Authenticated positive user ID required')

MODELS={'market':StrategyMarketEvidence,'analysis':StrategyReport,'baseline':StrategyBaseline}

def _canonical(kind,payload):
    model=MODELS[kind]
    result=model.model_validate(payload.model_dump(mode='python') if isinstance(payload,model) else payload)
    if kind=='market': return result,result.canonical_json()
    return result,json.dumps(result.model_dump(mode='json'),sort_keys=True,separators=(',',':'),allow_nan=False)

class OptionsPlatformStore(MonitoringStoreMixin):
    def __init__(self,store):
        self.store=store
        with self._db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS options_platform_artifacts (
                kind TEXT NOT NULL, id TEXT NOT NULL, user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id));
              CREATE INDEX IF NOT EXISTS options_platform_owner ON options_platform_artifacts(user_id,kind,created_at,id);
              CREATE TRIGGER IF NOT EXISTS options_platform_no_update BEFORE UPDATE ON options_platform_artifacts
                BEGIN SELECT RAISE(ABORT,'immutable platform artifact'); END;
              CREATE TRIGGER IF NOT EXISTS options_platform_no_delete BEFORE DELETE ON options_platform_artifacts
                BEGIN SELECT RAISE(ABORT,'immutable platform artifact'); END;
            ''')
        self._init_monitoring()

    @contextmanager
    def _db(self):
        try:
            with self.store.connect() as db:
                db.execute('PRAGMA busy_timeout=1000')
                yield db
        except sqlite3.OperationalError as exc:
            if (getattr(exc,'sqlite_errorcode',0)&255) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                raise PlatformStoreBusyError('Options storage busy') from None
            raise

    def _save(self,user_id,kind,payload,*,_check=None):
        _owner(user_id)
        value,text=_canonical(kind,payload)
        id=str(value.evidence_id if kind=='market' else value.report_id if kind=='analysis' else value.baseline_id)
        with self._db() as db:
            if _check: _check()
            db.execute('INSERT INTO options_platform_artifacts VALUES(?,?,?,?,?) ON CONFLICT(kind,id) DO NOTHING',
                (kind,id,user_id,datetime.now(UTC).isoformat(),text))
            row=db.execute('SELECT user_id,payload FROM options_platform_artifacts WHERE kind=? AND id=?',(kind,id)).fetchone()
            if row[0]!=user_id or row[1]!=text: raise PlatformConflictError('Artifact identity conflict')
            if _check: _check()
        return value

    def save_market_evidence(self,user_id,evidence,*,_check=None): return self._save(user_id,'market',evidence,_check=_check)
    def get_market_evidence(self,user_id,evidence_id): return self.get_report(user_id,'market',evidence_id)

    def save_report(self,user_id,kind,payload,*,_check=None):
        if kind!='analysis': raise ValueError('Unsupported report kind')
        value,_=_canonical(kind,payload)
        evidence=self.get_market_evidence(user_id,value.request.evidence_id)
        if evidence is None: raise ValueError('Owner market evidence required')
        if value.request.evidence_id not in value.evidence_ids: raise ValueError('Report evidence mismatch')
        ids=[value.request.stock_contract_id,value.request.call_contract_id]+([value.request.put_contract_id] if value.request.put_contract_id else [])
        by_id={x.instrument_id:x for x in evidence.contracts}
        expected=tuple(by_id[x] for x in ids if x in by_id)
        if value.selected_legs!=expected: raise ValueError('Report selection mismatch')
        if len(expected)!=len(ids) and (value.status!='cannot_assess' or 'contract_missing' not in value.reasons):
            raise ValueError('Missing selection requires incomplete report')
        for holding in value.holding_evidence:
            if (value.request.mode!='owned' or holding.evidence_id not in value.evidence_ids
                or holding.row_id!=value.request.holding_row_id or holding.stock_contract_id!=value.request.stock_contract_id):
                raise ValueError('Report holding reference mismatch')
        return self._save(user_id,kind,value,_check=_check)

    def get_report(self,user_id,kind,id):
        _owner(user_id)
        if kind not in MODELS: raise ValueError('Unsupported artifact kind')
        with self._db() as db:
            row=db.execute('SELECT payload FROM options_platform_artifacts WHERE user_id=? AND kind=? AND id=?',(user_id,kind,str(UUID(str(id))))).fetchone()
        return MODELS[kind].model_validate_json(row[0]) if row else None

    def list_reports(self,user_id,kind,*,limit=50,offset=0):
        _owner(user_id)
        if kind not in MODELS: raise ValueError('Unsupported artifact kind')
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=1000000: raise ValueError('Invalid pagination')
        with self._db() as db:
            rows=db.execute('SELECT payload FROM options_platform_artifacts WHERE user_id=? AND kind=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                (user_id,kind,limit,offset)).fetchall()
        return [MODELS[kind].model_validate_json(row[0]) for row in rows]

    def list_market_evidence(self,user_id,*,limit=50,offset=0): return self.list_reports(user_id,'market',limit=limit,offset=offset)

    def save_baseline(self,user_id,analysis_id,name):
        report=self.get_report(user_id,'analysis',analysis_id)
        if report is None: raise KeyError('Analysis not found')
        value=StrategyBaseline(analysis_id=report.report_id,name=name,created_at=datetime.now(UTC),calculation_version=report.calculation_version,evidence_ids=report.evidence_ids)
        return self._save(user_id,'baseline',value)

    def get_baseline(self,user_id,baseline_id): return self.get_report(user_id,'baseline',baseline_id)
    def list_baselines(self,user_id,*,limit=50,offset=0): return self.list_reports(user_id,'baseline',limit=limit,offset=offset)
