from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from test_portfolio_agent import app, client
from app.terminal.agent_registry import AGENT_REGISTRY

@pytest.fixture(autouse=True)
def _mock_risk_agent(monkeypatch):
    def build_risk(config, snapshot, tools, *, scope=None):
        return SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content={
            'answer': 'Risk analysis passed.',
            'evidence_ids': [snapshot['evidence_id']],
            'risk_report_ids': [snapshot['risk_report']['report_id']]})))
    mock = Mock(side_effect=build_risk)
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_risk', mock)
    return mock

def test_risk_policy_and_refresh(client, app):
    r=client.get('/api/options-agent/portfolio/risk-policy')
    assert r.status_code==200
    assert r.json()['policy']['revision']==0
    snapshot=client.post('/api/options-agent/portfolio/snapshot')
    assert snapshot.status_code==200
    assert snapshot.json()['risk_report']['policy_revision']==0

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from app.terminal import options_agent as module
from app.terminal.agent_scope import PortfolioAnswer, PortfolioChatRequest, make_scope
from app.terminal.portfolio_risk_contracts import RiskPolicySettings, RiskPolicyUpdate
from app.terminal.portfolio_risk_store import RiskStoreBusyError


def test_policy_api_owner_conflict_validation(client, app):
    body={'expected_revision':0,'policy':{'concentration_max_percent':'25.00'}}
    assert client.put('/api/options-agent/portfolio/risk-policy',json=body).json()['policy']['revision']==1
    assert client.put('/api/options-agent/portfolio/risk-policy',json=body).status_code==409
    for bad in ({**body,'user_id':2}, {'expected_revision':1,'policy':{'margin_max_percent':25}}, {'expected_revision':True,'policy':{}}):
        assert client.put('/api/options-agent/portfolio/risk-policy',json=bad).status_code==422
    assert client.post('/api/auth/register',json={'email':'risk-other@example.com','password':'test-password-123','display_name':'Other'}).status_code==200
    assert client.get('/api/options-agent/portfolio/risk-policy').json()['policy']['revision']==0
    assert client.put('/api/options-agent/portfolio/risk-policy',json=body).status_code==200


def test_policy_busy_sanitized(client, app, monkeypatch):
    def busy(*args): raise RiskStoreBusyError('private database path')
    monkeypatch.setattr(app.state.portfolio_risk_store,'update_policy',busy)
    response=client.put('/api/options-agent/portfolio/risk-policy',json={'expected_revision':0,'policy':{}})
    assert response.status_code==503 and response.headers['retry-after']=='1'
    assert 'private' not in response.text


def test_refresh_zero_model_and_saved_report(client, app):
    response=client.post('/api/options-agent/portfolio/snapshot')
    assert response.status_code==200,response.text
    value=response.json();app.state.mock_portfolio_agent.assert_not_called()
    report=app.state.portfolio_risk_store.get_report(1,value['risk_report']['report_id'])
    assert str(report.evidence_id)==value['evidence_id']
    with app.state.store.connect() as db:
        row=db.execute('SELECT status,detail FROM option_agent_runs').fetchone()
        assert row[0]=='completed' and json.loads(row[1])['risk_report_id']==str(report.report_id)


@pytest.mark.parametrize('bad_report',[None,str(uuid4())])
def test_wrong_or_absent_report_rejected(client,app,monkeypatch,bad_report):
    def build(config,snapshot,tools,*,scope=None):
        content={'answer':'ok','evidence_ids':[snapshot['evidence_id']]}
        if bad_report is not None: content['risk_report_ids']=[bad_report]
        return SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content=content)))
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_risk', build)
    assert client.post('/api/options-agent/portfolio/risk/chat',json={'message':'x'}).status_code==503
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM option_chat_turns').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM portfolio_risk_reports').fetchone()[0]==0
        assert 'risk_report_id' not in json.loads(db.execute('SELECT detail FROM option_agent_runs').fetchone()[0])


def test_captured_policy_edit_affects_next_run_only(client,app,monkeypatch):
    original=app.state.portfolio_service.fetch
    def fetch(*args,**kwargs):
        app.state.portfolio_risk_store.update_policy(1,RiskPolicyUpdate(expected_revision=0,policy=RiskPolicySettings(expiry_window_days=1)))
        return original(*args,**kwargs)
    monkeypatch.setattr(app.state.portfolio_service,'fetch',fetch)
    first=client.post('/api/options-agent/portfolio/snapshot')
    assert first.status_code==200,first.text
    assert first.json()['risk_report']['policy_revision']==0
    monkeypatch.setattr(app.state.portfolio_service,'fetch',original)
    app.state.options_agent.refresh_last[1]-=5.1
    second=client.post('/api/options-agent/portfolio/snapshot')
    assert second.json()['risk_report']['policy_revision']==1


def test_legacy_answer_and_history_remain_readable(client,app):
    assert PortfolioAnswer.model_validate({'answer':'old','evidence_ids':[uuid4()]}).risk_report_ids==[]
    cid=str(uuid4());legacy={'schema_version':'portfolio.v1','scope':'portfolio'}
    with app.state.store.connect() as db:
        db.execute('INSERT INTO option_chat_conversations VALUES (?,?,?,?)',(cid,1,json.dumps(legacy),'old'))
        db.execute('INSERT INTO option_chat_turns(conversation_id,user_id,message,answer,evidence,created_at) VALUES (?,?,?,?,?,?)',(cid,1,'old question','old answer','{}','old'))
    assert client.get('/api/options-agent/conversations/'+cid).json()['turns'][0]['answer']=='old answer'
    assert make_scope('portfolio',None).prompt_version=='portfolio.2'
    res = client.post('/api/options-agent/portfolio/chat',json={'message':'new','conversation_id':cid})
    assert res.status_code == 409
    assert 'conversation_scope_changed' in str(res.json()['detail'])


@pytest.mark.parametrize('interruption',['cancel','logout'])
def test_refresh_final_commit_fence_rolls_back(app,monkeypatch,interruption):
    agent=app.state.options_agent
    entered=threading.Event();release=threading.Event()
    original=agent._assert_generation
    calls=[]
    session=app.state.market.get_session(1)
    def check(uid,generation):
        calls.append(True)
        # Initial response validation is call 1, publication entry call 2,
        # final transaction publication fence is call 3.
        if len(calls)==3:
            entered.set();release.wait(3)
        original(uid,generation)
    monkeypatch.setattr(agent,'_assert_generation',check)
    async def scenario():
        async with agent.mcp.lifespan():
            request=asyncio.create_task(agent.portfolio_snapshot(1))
            try:
                async with asyncio.timeout(2):
                    while not entered.is_set(): await asyncio.sleep(.001)
                if interruption=='cancel': request.cancel()
                else: session.generation=str(uuid4())
                release.set()
                if interruption=='cancel':
                    with pytest.raises(asyncio.CancelledError): await request
                else:
                    from fastapi import HTTPException
                    with pytest.raises(HTTPException): await request
            finally:
                release.set()
                await asyncio.gather(*agent.workers.get(1,()),return_exceptions=True)
            with app.state.store.connect() as db:
                assert db.execute('SELECT COUNT(*) FROM portfolio_risk_reports').fetchone()[0]==0
                assert db.execute("SELECT COUNT(*) FROM option_agent_runs WHERE status='completed'").fetchone()[0]==0
    asyncio.run(scenario())


def test_malformed_envelope_never_published(client,app,monkeypatch):
    from app.terminal.options_mcp import MCPConnection
    monkeypatch.setattr(MCPConnection,'portfolio_snapshot',AsyncMock(return_value={'evidence_id':str(uuid4()),'risk_report':{}}))
    assert client.post('/api/options-agent/portfolio/snapshot').status_code==503
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM portfolio_risk_reports').fetchone()[0]==0


def test_report_counts_toward_context_budget(client,app,monkeypatch):
    from app.terminal import portfolio_risk
    original=portfolio_risk.evaluate_portfolio_risk
    def evaluate(*args,**kwargs):
        report=original(*args,**kwargs)
        return report.model_copy(update={'limitations':['untrusted'*10000]})
    monkeypatch.setattr(portfolio_risk,'evaluate_portfolio_risk',evaluate)
    response=client.post('/api/options-agent/portfolio/risk/chat',json={'message':'x'})
    assert response.status_code==503
    app.state.mock_portfolio_agent.assert_not_called()


def test_actual_sqlite_lock_exhaustion_sanitized(client,app):
    with app.state.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        response=client.put('/api/options-agent/portfolio/risk-policy',json={'expected_revision':0,'policy':{}})
        assert response.status_code==503 and response.headers['retry-after']=='1'
        assert 'database' not in response.text.lower()


def test_policy_authentication(app):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    app.state.config.app_password=SecretStr('long-test-password')
    with TestClient(app) as client:
        assert client.get('/api/options-agent/portfolio/risk-policy').status_code==401
        assert client.put('/api/options-agent/portfolio/risk-policy',json={'expected_revision':0,'policy':{}}).status_code==401


def test_publication_busy_returns_retryable_without_report(client,app,monkeypatch):
    def busy(*args): raise RiskStoreBusyError('private storage error')
    monkeypatch.setattr(app.state.options_agent.risk_store,'save_report',busy)
    response=client.post('/api/options-agent/portfolio/snapshot')
    assert response.status_code==503 and response.headers['retry-after']=='1'
    assert 'private' not in response.text
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM portfolio_risk_reports').fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM option_agent_runs WHERE status='completed'").fetchone()[0]==0


def test_policy_get_actual_exclusive_read_lock_is_retryable(client,app,tmp_path,monkeypatch):
    import sqlite3
    import time
    from app.terminal.store import Store
    from app.terminal.portfolio_risk_store import PortfolioRiskStore
    # Use a real separate risk database so authentication's reads are unaffected.
    # DELETE journaling permits an EXCLUSIVE lock that blocks reads; normal WAL
    # writers intentionally do not exercise this exhausted-read-lock path.
    risk=PortfolioRiskStore(Store(tmp_path/'locked-risk.sqlite3',100))
    monkeypatch.setattr(app.state,'portfolio_risk_store',risk)
    with sqlite3.connect(risk.store.path) as lock:
        assert lock.execute('PRAGMA journal_mode=DELETE').fetchone()[0]=='delete'
        lock.execute('BEGIN EXCLUSIVE')
        started=time.monotonic()
        response=client.get('/api/options-agent/portfolio/risk-policy')
        elapsed=time.monotonic()-started
        assert response.status_code==503 and response.headers['retry-after']=='1'
        assert elapsed<3
        assert 'database' not in response.text.lower() and 'locked-risk' not in response.text
    assert client.get('/api/options-agent/portfolio/risk-policy').status_code==200


def test_portfolio_refresh_prompt_version(client,app):
    assert client.post('/api/options-agent/portfolio/snapshot').status_code==200
    with app.state.store.connect() as db:
        detail=json.loads(db.execute("SELECT detail FROM option_agent_runs WHERE kind='snapshot'").fetchone()[0])
    assert detail['prompt_version']=='portfolio.2'


def test_new_history_references_canonical_report_and_hydrates_owner(client, app):
    response = client.post('/api/options-agent/portfolio/risk/chat', json={'message': 'summarize'})
    assert response.status_code == 200, response.text
    value = response.json()
    with app.state.store.connect() as db:
        evidence = json.loads(db.execute('SELECT evidence FROM option_chat_turns').fetchone()[0])
    assert 'risk_report' not in evidence
    assert evidence['risk_report_id'] == value['risk_report_ids'][0]
    history = app.state.options_agent.history(1, value['conversation_id'])
    assert history['turns'][0]['risk_snapshot'] == value['risk_snapshot']
    assert app.state.portfolio_risk_store.get_report(2, evidence['risk_report_id']) is None
    # Embedded history from before normalization remains readable.
    with app.state.store.connect() as db:
        db.execute('UPDATE option_chat_turns SET evidence=?', (json.dumps(value['risk_snapshot']),))
    assert app.state.options_agent.history(1, value['conversation_id'])['turns'][0]['risk_snapshot'] == value['risk_snapshot']
    # A reference cannot hydrate a canonical report owned by another user.
    with app.state.store.connect() as db:
        db.execute('UPDATE option_chat_turns SET evidence=?', (json.dumps(evidence),))
        db.execute('DROP TRIGGER portfolio_risk_reports_immutable')
        db.execute('UPDATE portfolio_risk_reports SET user_id=2')
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as missing:
        app.state.options_agent.history(1, value['conversation_id'])
    assert missing.value.status_code == 503


@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('endpoint', ['snapshot', 'risk/chat'])
def test_production_risk_diagnostics_breach_and_evaluation_failure(client, app, monkeypatch, caplog, failure, endpoint):
    from app.terminal import portfolio_risk
    import logging
    caplog.set_level(logging.INFO)
    from datetime import UTC, datetime
    from app.terminal.portfolio_contracts import PortfolioSnapshot, PortfolioSection, PortfolioRow
    app.state.portfolio_risk_store.update_policy(1, RiskPolicyUpdate(expected_revision=0,
        policy=RiskPolicySettings(concentration_max_percent='60', max_observation_age_seconds=60)))
    def fetch(*args, **kwargs):
        now = datetime.now(UTC)
        rows = [PortfolioRow(row_id=str(i), quantity='1', market_value=value, currency='INR',
            identity_verified=True, underlying_key=str(i), underlying_identity_basis='catalogue_match',
            symbol='PROVIDER_SENTINEL') for i, value in enumerate(['987654321', '1'])]
        return PortfolioSnapshot(retrieval_started_at=now, retrieval_finished_at=now, source_observed_at=now,
            sections={name: PortfolioSection(state='available', rows=rows if name == 'holdings' else [],
                retrieval_started_at=now, retrieval_finished_at=now) for name in ('holdings', 'positions', 'funds')})
    monkeypatch.setattr(app.state.portfolio_service, 'fetch', fetch)
    if failure:
        def evaluate(*args):
            raise ValueError('EXCEPTION_SENTINEL financial=987654321 provider=PROVIDER_SENTINEL')
        monkeypatch.setattr(portfolio_risk, 'evaluate_portfolio_risk', evaluate)
    response = client.post('/api/options-agent/portfolio/' + endpoint, **({'json': {'message': 'summarize'}} if 'chat' in endpoint else {}))
    assert response.status_code == (503 if failure else 200)
    events = [json.loads(record.message.split('portfolio_risk ', 1)[1])
              for record in caplog.records if record.message.startswith('portfolio_risk ')]
    assert events
    trace = events[-1]
    assert trace['evidence_id'] is not None
    assert trace['policy_revision'] == 1
    assert trace['calculation_version'] == 'portfolio-risk.1'
    assert trace['enabled_count'] == 4
    assert trace['assessed_count'] == (None if failure else 1)
    assert trace['outcome'] == ('operational_failure' if failure else 'breach')
    assert trace['failure_stage'] == ('evaluation' if failure else None)
    serialized = json.dumps(events)
    assert all(value not in serialized for value in ('987654321', 'EXCEPTION_SENTINEL', 'PROVIDER_SENTINEL', 'measured'))
    with app.state.store.connect() as db:
        detail = json.loads(db.execute('SELECT detail FROM option_agent_runs').fetchone()[0])
    assert detail['risk_diagnostics']['outcome'] == ('operational_failure' if failure else 'breach')
    assert detail['risk_diagnostics']['failure_stage'] == ('evaluation' if failure else None)
    if not failure:
        assert detail['risk_diagnostics']['report_id'] == (response.json()['risk_snapshot'] if 'risk' in endpoint else response.json())['risk_report']['report_id']

@pytest.mark.parametrize('interruption', ['cancel', 'deadline', 'logout'])
def test_chat_history_hydration_is_nonblocking_and_fenced(client, app, monkeypatch, interruption):
    response = client.post('/api/options-agent/portfolio/risk/chat', json={'message': 'seed history'})
    assert response.status_code == 200, response.text
    conversation_id = response.json()['conversation_id']
    agent = app.state.options_agent
    entered = threading.Event()
    release = threading.Event()
    original = app.state.portfolio_risk_store.get_report
    def blocked_report(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(app.state.portfolio_risk_store, 'get_report', blocked_report)
    if interruption == 'deadline':
        monkeypatch.setattr(agent, 'deadline_seconds', .15)
    app.state.mock_portfolio_agent.reset_mock()
    async def scenario():
        request = asyncio.create_task(agent.portfolio_risk_chat(1, PortfolioChatRequest(
            message='continue', conversation_id=conversation_id)))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(.001)
            # Reaching this point while the database read is blocked proves the
            # event loop can continue scheduling unrelated work.
            assert not request.done()
            assert 1 in agent.active
            if interruption == 'cancel':
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
            elif interruption == 'deadline':
                from fastapi import HTTPException
                with pytest.raises(HTTPException) as error:
                    await request
                assert error.value.status_code == 504
            else:
                app.state.market.get_session(1).generation = str(uuid4())
            if interruption != 'logout':
                assert 1 in agent.active  # Worker retains admission until it exits.
            release.set()
            if interruption == 'logout':
                from fastapi import HTTPException
                with pytest.raises(HTTPException):
                    await request
        finally:
            release.set()
            await asyncio.gather(request, return_exceptions=True)
            while agent.workers.get(1):
                await asyncio.gather(*tuple(agent.workers[1]), return_exceptions=True)
        app.state.mock_portfolio_agent.assert_not_called()
        with app.state.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM option_chat_turns').fetchone()[0] == 1
            assert db.execute('SELECT COUNT(*) FROM portfolio_risk_reports').fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM option_agent_runs WHERE status='completed'").fetchone()[0] == 1
    asyncio.run(scenario())
