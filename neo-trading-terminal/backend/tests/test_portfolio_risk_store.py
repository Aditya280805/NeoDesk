from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4
import pytest
from app.terminal.store import Store
from app.terminal.portfolio_risk_contracts import RiskPolicySettings, RiskPolicyUpdate, RiskReport, RiskFinding, RiskCoverage
from app.terminal.portfolio_risk_store import PortfolioRiskStore, PolicyConflictError, ReportConflictError

@pytest.fixture
def risk(tmp_path):
    return PortfolioRiskStore(Store(tmp_path/'test.sqlite3',100))

def report():
    return RiskReport(evidence_id=uuid4(),policy_revision=0,evaluated_at=datetime.now(UTC),summary='cannot_assess',coverage=RiskCoverage(passed=0,breached=0,cannot_assess=4,disabled=0),findings=[RiskFinding(code=c,enabled=True,outcome='cannot_assess') for c in ('concentration','expiry','margin','loss')])

def test_policy_and_concurrency(risk):
    assert risk.get_policy(1).revision==0
    update=RiskPolicyUpdate(expected_revision=0,policy=RiskPolicySettings(margin_max_percent='120.25'))
    def save(_):
        try: return risk.update_policy(1,update).revision
        except PolicyConflictError: return 'conflict'
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(save,range(2)))
    assert sorted(results,key=str)==[1,'conflict']
    assert risk.get_policy(1).margin_max_percent=='120.25'
    assert risk.get_policy(2).revision==0
    with pytest.raises(PolicyConflictError): risk.update_policy(1,update)

def test_report_isolation_idempotence_rollback(risk):
    item=report()
    with risk.store.connect() as db:
        db.execute("BEGIN")
        risk.save_report(db,1,item)
        risk.save_report(db,1,item)
    assert risk.get_report(1,item.report_id)==item
    assert risk.get_report(2,item.report_id) is None
    with pytest.raises(ReportConflictError):
        with risk.store.connect() as db:
            db.execute("BEGIN")
            risk.save_report(db,2,item)
    with pytest.raises(ReportConflictError):
        with risk.store.connect() as db:
            db.execute("BEGIN")
            risk.save_report(db,1,item.model_copy(update={'policy_revision':1}))
    other=report()
    with pytest.raises(RuntimeError):
        with risk.store.connect() as db:
            db.execute("BEGIN")
            risk.save_report(db,1,other)
            raise RuntimeError()
    assert risk.get_report(1,other.report_id) is None

@pytest.mark.parametrize('embedded', [False, True])
def test_migration_and_maintenance(risk, embedded):
    keep_history,keep_run,remove=report(),report(),report()
    import json
    with risk.store.connect() as db:
        db.execute('CREATE TABLE option_chat_turns (evidence TEXT, answer TEXT)')
        db.execute('CREATE TABLE option_agent_runs (detail TEXT)')
        db.execute('INSERT INTO option_chat_turns VALUES (?,?)',(json.dumps({'portfolio':{'risk_report':{'report_id':str(keep_history.report_id)}}} if embedded else {'risk_report_id':str(keep_history.report_id)}),'Funds evidence is available; exchange freshness is unknown.'))
        db.execute('INSERT INTO option_agent_runs VALUES (?)',(json.dumps({'report_ids':[str(keep_run.report_id)]}),))
        for item in (keep_history,keep_run,remove): risk.save_report(db,1,item)
        # Creation timestamps are normally immutable; seed old rows through a
        # test-only trigger removal to avoid dependence on wall-clock delays.
        db.execute('DROP TRIGGER portfolio_risk_reports_immutable')
        db.execute("UPDATE portfolio_risk_reports SET created_at='2000-01-01T00:00:00+00:00'")
    reopened=PortfolioRiskStore(risk.store)
    assert reopened.prune_reports(30)==[str(remove.report_id)]
    assert reopened.get_report(1,remove.report_id)==remove
    assert reopened.prune_reports(30,apply=True)==[str(remove.report_id)]
    assert reopened.get_report(1,remove.report_id) is None
    assert reopened.get_report(1,keep_history.report_id)==keep_history
    assert reopened.get_report(1,keep_run.report_id)==keep_run
    with risk.store.connect() as db:
        assert db.execute('SELECT count(*) FROM option_chat_turns').fetchone()[0]==1


def test_owner_and_transaction_required(risk):
    for user_id in (None,True,0,-1,'1'):
        with pytest.raises(ValueError): risk.get_policy(user_id)
    with risk.store.connect() as db:
        with pytest.raises(ValueError,match='active caller transaction'):
            risk.save_report(db,1,report())


def test_lock_wait_is_bounded_and_sanitized(risk):
    from app.terminal.portfolio_risk_store import RiskStoreBusyError
    import time
    with risk.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        start=time.monotonic()
        with pytest.raises(RiskStoreBusyError,match='^Risk storage is busy; retry later$'):
            risk.update_policy(1,RiskPolicyUpdate(expected_revision=0,policy=RiskPolicySettings()))
        assert time.monotonic()-start<3

def test_additive_migration_over_phase1_history(tmp_path):
    import json
    store=Store(tmp_path/'phase1.sqlite3',100)
    with store.connect() as db:
        db.executescript('''
            CREATE TABLE option_conversations (id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE option_chat_turns (id INTEGER PRIMARY KEY,conversation_id TEXT,user_id INTEGER,message TEXT,answer TEXT,evidence TEXT,created_at TEXT);
            CREATE TABLE option_agent_runs (id TEXT PRIMARY KEY,user_id INTEGER,kind TEXT,status TEXT,created_at TEXT,detail TEXT);
        ''')
        db.execute('INSERT INTO option_chat_turns VALUES (1,?,?,?,?,?,?)',('old',1,'question',json.dumps({'text':'answer'}),json.dumps({'portfolio':{'schema_version':'portfolio.v1'}}),'2026-01-01'))
        before=tuple(db.execute('SELECT * FROM option_chat_turns').fetchone())
    risk=PortfolioRiskStore(store)
    assert risk.get_policy(1).revision==0
    with store.connect() as db:
        assert tuple(db.execute('SELECT * FROM option_chat_turns').fetchone())==before
