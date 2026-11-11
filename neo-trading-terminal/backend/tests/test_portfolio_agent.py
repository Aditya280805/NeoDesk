"""Portfolio scope API and real SDK transport checks; fixtures never leave localhost."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth.router import _clear_rate_limits
from app.core.config import Settings
from app.terminal import options_agent as module
from app.terminal.agent_registry import AGENT_REGISTRY
from app.terminal.agent_scope import PortfolioChatRequest, PortfolioAnswer, make_scope, specialist_scope
from app.terminal import specialist_agents
from app.terminal.server import create_app

@pytest.fixture
def app(tmp_path, monkeypatch):
    _clear_rate_limits()
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, environment='test', app_password=None,
        kotak_consumer_key=None, openai_api_key=SecretStr('fixture'), options_mcp_port=0))
    chain_fetch = Mock(side_effect=AssertionError('Portfolio must not fetch chain'))
    def call(method, user_id, **kwargs):
        if method not in ('limits','holdings','positions','order_report'):
            return chain_fetch(method, user_id)
        return {'Net':'10'} if method == 'limits' else {'data':[]}
    monkeypatch.setattr(app.state.market, 'call', Mock(side_effect=call))
    app.state.chain_fetch = chain_fetch
    app.state.market.get_session(1).broker = MagicMock(is_authenticated=True)
    app.state.market.get_session(1).source = 'kotak'
    def build(config, snapshot, tools, **kwargs):
        return SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content={
            'answer':'Funds evidence is available; exchange freshness is unknown.', 'evidence_ids':[snapshot['evidence_id']]})))
    mock_portfolio = Mock(side_effect=build)
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_analysis', mock_portfolio)
    app.state.mock_portfolio_agent = mock_portfolio
    return app

@pytest.fixture
def client(app):
    with TestClient(app, headers={'X-NeoDesk':'1'}) as client:
        assert client.post('/api/auth/register', json={'email':'portfolio@example.com','password':'test-password-123','display_name':'Portfolio'}).status_code == 200
        yield client

def test_portfolio_contract():
    assert make_scope('portfolio', None).stored_context == {'schema_version':'portfolio.v1','scope':'portfolio'}
    assert specialist_scope('portfolio', None).stored_context == {'scope': 'portfolio', 'agent_id': 'portfolio_analysis', 'contract_version': 'analysis.1'}

def test_portfolio_authenticated_snapshot_chat_history(client, app):
    assert client.post('/api/options-agent/portfolio/snapshot',json={'underlying':'NIFTY'}).status_code == 422
    assert client.post('/api/options-agent/portfolio/snapshot').status_code == 200
    reply = client.post('/api/options-agent/portfolio/chat', json={'message':'Summarize'})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body['evidence_ids'] == [body['portfolio_snapshot']['evidence_id']]
    assert body['read_only'] is True and 'snapshot_ids' not in body
    assert body['agent_id'] == 'portfolio_analysis'
    assert app.state.chain_fetch.call_count == 0
    history = client.get('/api/options-agent/conversations/'+body['conversation_id']).json()
    assert history['context'] == {'scope': 'portfolio', 'agent_id': 'portfolio_analysis', 'contract_version': 'analysis.1'}
    assert history['turns'][0]['portfolio_snapshot'] == body['portfolio_snapshot']
    assert 'snapshot' not in history['turns'][0]
    record = client.get('/api/options-agent/runs/'+body['run_id']).json()['detail']
    assert record['scope'] == 'portfolio' and record['agent_id'] == 'portfolio_analysis'
    assert record['evidence_id'] == body['evidence_ids'][0]
    assert client.post('/api/options-agent/chat', json={'message':'reuse','conversation_id':body['conversation_id']}).status_code == 409
    assert client.post('/api/auth/register', json={'email':'other@example.com','password':'test-password-123','display_name':'Other'}).status_code == 200
    assert client.get('/api/options-agent/conversations/'+body['conversation_id']).status_code == 404
    assert client.post('/api/options-agent/portfolio/chat', json={'message':'reuse','conversation_id':body['conversation_id']}).status_code == 404

@pytest.mark.parametrize('bad', [{'message':' '},{'message':'x','underlying':'NIFTY'},{'message':'x','context':{}},{'message':'x','evidence_id':str(uuid4())}])
def test_extra_and_empty_request_fields_rejected(client,bad):
    assert client.post('/api/options-agent/portfolio/chat',json=bad).status_code == 422

def test_portfolio_authentication(app):
    app.state.config.app_password = SecretStr('long-test-password')
    with TestClient(app) as client:
        assert client.post('/api/options-agent/portfolio/snapshot').status_code == 401
        assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 401

@pytest.mark.parametrize('content', [{}, {'answer':'ok'}, {'answer':'ok','evidence_ids':[]}, {'answer':'ok','evidence_ids':[str(uuid4())]}, {'answer':'','evidence_ids':[str(uuid4())]}, {'answer':'ok','snapshot_ids':[str(uuid4())]}])
def test_bad_evidence_never_persisted(client,app,content,monkeypatch):
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_analysis', lambda *a,**kw:SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content=content))))
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 503
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM option_chat_turns').fetchone()[0] == 0

def test_incomplete_run_rejected(client,app,monkeypatch):
    from agno.run.base import RunStatus
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_analysis', lambda *a,**kw:SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(status=RunStatus.error,content={}))))
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 503

def test_generation_rechecked_after_model(client,app,monkeypatch):
    async def changed():
        app.state.market.get_session(1).generation = str(uuid4())
        return SimpleNamespace(content={'answer':'ok','evidence_ids':[str(uuid4())]})
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_analysis', lambda *a,**kw:SimpleNamespace(arun=changed))
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 503
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM option_chat_turns').fetchone()[0] == 0

def test_shared_admission(client,app):
    agent=app.state.options_agent
    agent.active.add(1)
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 409
    assert client.post('/api/options-agent/portfolio/snapshot').status_code == 409
    agent.active.clear()
    agent.refresh_active.add(1)
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 409
    agent.refresh_active.clear()
    import time
    agent.recent.extend((time.monotonic(),1) for _ in range(6))
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 429
    assert client.post('/api/options-agent/chat',json={'message':'x'}).status_code == 429
    agent.recent.clear()
    agent.active.update({2,3,4,5})
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 429
    assert client.post('/api/options-agent/portfolio/snapshot').status_code == 429
    agent.active.clear()
    assert client.post('/api/options-agent/portfolio/snapshot').status_code == 200
    assert client.post('/api/options-agent/snapshot',json={}).status_code == 429

def test_context_oversize_blocks_model(client,app,monkeypatch):
    original=app.state.market.call.side_effect
    def large_orders(method,user_id,**kwargs):
        if method=='order_report':
            return {'data':[{'trdSym':str(i)+'provider-untrusted'*8,'qty':'1'} for i in range(150)]}
        return original(method,user_id,**kwargs)
    app.state.market.call.side_effect=large_orders
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code == 503
    app.state.mock_portfolio_agent.assert_not_called()
    with app.state.store.connect() as db:
        assert json.loads(db.execute('SELECT detail FROM option_agent_runs').fetchone()[0])['failure_reason'] in ('context_limit', 'context_budget')

def test_oldest_history_trimmed_and_section_states_preserved(client,app,monkeypatch):
    first=client.post('/api/options-agent/portfolio/chat',json={'message':'first'}).json()
    with app.state.store.connect() as db:
        for i in range(4):
            db.execute('INSERT INTO option_chat_turns(conversation_id,user_id,message,answer,evidence,created_at) VALUES (?,?,?,?,?,?)',
                (first['conversation_id'],1,str(i)+'x'*20000,'previous-untrusted',json.dumps(first['portfolio_snapshot']),'fixture'))
    prompts=[]
    def capture(config,snapshot,tools,**kw):
        async def run(prompt):
            prompts.append(prompt)
            return SimpleNamespace(content={'answer':'ok','evidence_ids':[snapshot['evidence_id']]})
        return SimpleNamespace(arun=run)
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_analysis', capture)
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'next','conversation_id':first['conversation_id']}).status_code == 200
    prompt=json.loads(prompts[0]); assert len(prompts[0].encode())<=65536
    assert len(prompt['previous_conversation'])<4
    snapshot=prompt['current_portfolio_snapshot']
    assert snapshot['sections']['holdings']['state']=='available' and snapshot['sections']['holdings']['rows']==[]
    app.state.market.get_session(1).portfolio_cache=None
    original=app.state.market.call.side_effect
    app.state.market.call.side_effect=lambda method,user_id,**kwargs:{} if method=='limits' else original(method,user_id)
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'missing funds'}).status_code == 200
    assert json.loads(prompts[-1])['current_portfolio_snapshot']['sections']['funds']['state'] != 'available'

@pytest.mark.parametrize('provider',['gemini','openai'])
def test_real_provider_serialization_portfolio(client,app,monkeypatch,provider):
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_analysis', specialist_agents.build_portfolio_analysis_agent)
    original=app.state.market.call.side_effect
    def provider_data(method,user_id,**kwargs):
        return {'data':[{'trdSym':'provider-untrusted','qty':'1'}]} if method=='order_report' else original(method,user_id,**kwargs)
    app.state.market.call.side_effect=provider_data
    calls=[]; errors=[]
    def respond(request):
        try:
            payload=json.loads(request.content); calls.append(payload)
            if provider=='gemini':
                declarations=payload['tools'][0]['functionDeclarations']
                assert [d['name'] for d in declarations]==['get_portfolio_analysis_snapshot']
                assert 'evidence_ids' in payload['generationConfig']['responseSchema']['properties']
                assert 'previous-untrusted' not in str(payload.get('systemInstruction',{}))
                assert 'provider-untrusted' not in str(payload.get('systemInstruction',{}))
                assert 'provider-untrusted' in str(payload['contents'])
                if len(calls)==1:
                    parts=[{'functionCall':{'name':'get_portfolio_analysis_snapshot','args':{},'id':'portfolio-call'},'thoughtSignature':'Zml4dHVyZQ=='}]
                else:
                    responses=[p['functionResponse'] for c in payload['contents'] for p in c['parts'] if 'functionResponse' in p]
                    assert responses[0]['name']=='get_portfolio_analysis_snapshot'
                    text=next(p['text'] for c in payload['contents'] for p in c['parts'] if 'text' in p and 'current_portfolio_snapshot' in p['text'])
                    evidence=json.loads(text)['current_portfolio_snapshot']['evidence_id']
                    assert evidence in str(responses)
                    parts=[{'text':json.dumps({'answer':'Read-only portfolio evidence.','evidence_ids':[evidence]})}]
                return httpx.Response(200,json={'candidates':[{'content':{'role':'model','parts':parts},'finishReason':'STOP'}],
                    'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':40,'thoughtsTokenCount':60,'totalTokenCount':200}})
            assert [t['function']['name'] for t in payload['tools']]==['get_portfolio_analysis_snapshot']
            assert payload['max_completion_tokens']==900
            assert 'evidence_ids' in payload['response_format']['json_schema']['schema']['properties']
            privileged=[m for m in payload['messages'] if m['role'] in ('system','developer')]
            assert 'previous-untrusted' not in str(privileged)
            assert 'provider-untrusted' not in str(privileged)
            assert 'provider-untrusted' in str(payload['messages'])
            message=next(m['content'] for m in payload['messages'] if m['role']=='user' and 'current_portfolio_snapshot' in m['content'])
            evidence=json.loads(message)['current_portfolio_snapshot']['evidence_id']
            return httpx.Response(200,json={'id':'fixture','object':'chat.completion','created':1,'model':'gpt-4.1-mini',
                'choices':[{'index':0,'message':{'role':'assistant','content':json.dumps({'answer':'Read-only portfolio evidence.','evidence_ids':[evidence]})},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':100,'completion_tokens':40,'total_tokens':140}})
        except Exception as e:
            errors.append(repr(e)); raise
    if provider=='gemini':
        from google import genai
        from google.genai import types
        sdk=genai.Client(api_key='fixture',http_options=types.HttpOptions(httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
        monkeypatch.setattr('app.terminal.options_gemini.BoundedGemini.get_client',lambda self:sdk)
        app.state.config.gemini_api_key=SecretStr('fixture');app.state.config.options_agent_provider='gemini'
    else:
        from openai import AsyncOpenAI
        sdk=AsyncOpenAI(api_key='fixture',max_retries=0,http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        monkeypatch.setattr('app.terminal.options_model.BoundedOpenAIChat.get_async_client',lambda self:sdk)
    reply=client.post('/api/options-agent/portfolio/chat',json={'message':'previous-untrusted'})
    assert reply.status_code==200,(reply.text,errors)
    body=reply.json(); assert body['evidence_ids']==[body['portfolio_snapshot']['evidence_id']]
    assert len(calls)==(2 if provider=='gemini' else 1)
    if provider=='gemini':
        asyncio.run(sdk.aio.aclose());sdk.close()
    else: asyncio.run(sdk.close())

REAL_BUILD_AGENT=specialist_agents.build_portfolio_analysis_agent



def test_generation_rechecked_immediately_before_persistence(client,app,monkeypatch):
    checks=[]
    original=app.state.options_agent._assert_generation
    def check(uid,generation):
        checks.append(True)
        if len(checks)==3:
            app.state.market.get_session(uid).generation=str(uuid4())
        original(uid,generation)
    monkeypatch.setattr(app.state.options_agent,'_assert_generation',check)
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'x'}).status_code==503
    assert len(checks)==3
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM option_chat_turns').fetchone()[0]==0


def test_scope_instructions_are_static_and_enforce_read_only():
    instructions=' '.join(make_scope('portfolio',None).instructions)
    for term in ('unavailable', 'empty', 'zero', 'trades', 'strategy', 'freshness', 'untrusted'):
        assert term in instructions
    assert 'previous-untrusted' not in instructions


def test_preexisting_chain_history_keeps_exact_shape(client,app):
    cid=str(uuid4());context={'underlying':'NIFTY','exchange':'nse_fo','expiry':None}
    legacy={'snapshot_id':'old-chain-evidence','rows':[],'summary':{'put_call_ratio':None}}
    with app.state.store.connect() as db:
        db.execute('INSERT INTO option_chat_conversations VALUES (?,?,?,?)',(cid,1,json.dumps(context),'old-time'))
        db.execute('INSERT INTO option_chat_turns(conversation_id,user_id,message,answer,evidence,created_at) VALUES (?,?,?,?,?,?)',
            (cid,1,'old question','old answer',json.dumps(legacy),'old-time'))
    assert client.get('/api/options-agent/conversations/'+cid).json()=={
        'conversation_id':cid,'context':context,'turns':[{'message':'old question','answer':'old answer','snapshot':legacy,'created_at':'old-time'}]}
    assert client.post('/api/options-agent/portfolio/chat',json={'message':'reuse','conversation_id':cid}).status_code==409


def test_final_review_initial_generation_lock_is_deadline_bounded(app):
    import threading,time
    from fastapi import HTTPException
    async def scenario():
        agent=app.state.options_agent; agent.deadline_seconds=.03
        entered=threading.Event(); release=threading.Event()
        def holder():
            with app.state.market.lock:
                entered.set(); release.wait(.3)
        thread=threading.Thread(target=holder);thread.start();assert entered.wait(2)
        heartbeat=[]
        async def beat():
            await asyncio.sleep(.005);heartbeat.append(time.monotonic())
        started=time.monotonic(); pulse=asyncio.create_task(beat())
        try:
            with pytest.raises(HTTPException) as error: await agent.portfolio_snapshot(1)
            elapsed=time.monotonic()-started
            await pulse
            assert heartbeat[0]-started<.1
            assert elapsed<.15 and error.value.status_code==504
        finally:
            release.set();thread.join(2)
    asyncio.run(scenario())


def test_final_review_manual_refresh_bypasses_chat_cache(client,app):
    first=client.post('/api/options-agent/portfolio/snapshot').json()
    app.state.options_agent.refresh_last[1]-=5.1
    app.state.market.call.side_effect=lambda method,user_id,**kwargs: {'Net':'25'} if method=='limits' else {'data':[]}
    cached=client.post('/api/options-agent/portfolio/chat',json={'message':'cached'}).json()
    assert cached['portfolio_snapshot']['summary']['available']=='10'
    refreshed=client.post('/api/options-agent/portfolio/snapshot')
    assert refreshed.status_code==200,refreshed.text
    assert refreshed.json()['summary']['available']=='25'
    assert first['source_observed_at']==cached['portfolio_snapshot']['source_observed_at']


def test_final_review_cancelled_generation_worker_retains_admission(app,monkeypatch):
    import threading
    async def scenario():
        agent=app.state.options_agent
        entered=threading.Event();release=threading.Event()
        original=agent._generation
        def blocked(uid,scope):
            entered.set();release.wait(3)
            return original(uid,scope)
        monkeypatch.setattr(agent,'_generation',blocked)
        request=asyncio.create_task(agent.portfolio_snapshot(1))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set(): await asyncio.sleep(.001)
            request.cancel()
            with pytest.raises(asyncio.CancelledError): await request
            assert 1 in agent.refresh_active
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as error: await agent.portfolio_snapshot(1)
            assert error.value.status_code==409
        finally:
            release.set()
            await asyncio.gather(*agent.workers.get(1,()),return_exceptions=True)
            await asyncio.sleep(0)
        assert 1 not in agent.refresh_active
        with app.state.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM option_chat_turns').fetchone()[0]==0
    asyncio.run(scenario())


@pytest.mark.parametrize('blocked_assertion', [4, 5, 6])
@pytest.mark.parametrize('interruption', ['cancel', 'deadline'])
def test_final_review_cancelled_persistence_rolls_back(app,monkeypatch,blocked_assertion,interruption):
    import threading
    from contextlib import asynccontextmanager
    agent=app.state.options_agent
    entered=threading.Event();release=threading.Event()
    original_connect=app.state.store.connect
    original_check=agent._assert_generation
    checks=[]
    if interruption=='deadline': agent.deadline_seconds=.3
    # Cover both post-insertion and final pre-commit generation assertions.
    def check(uid,generation):
        checks.append(True)
        original_check(uid,generation)
        if len(checks)==blocked_assertion:
            entered.set();release.wait(3)
    monkeypatch.setattr(agent,'_assert_generation',check)
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    from datetime import UTC,datetime
    now=datetime.now(UTC)
    snapshot=json.loads(PortfolioSnapshot(retrieval_started_at=now,retrieval_finished_at=now,source_observed_at=now).model_dump_json())
    from app.terminal.portfolio_risk import evaluate_portfolio_risk
    from app.terminal.portfolio_risk_contracts import RiskPolicy
    snapshot['risk_report']=json.loads(evaluate_portfolio_risk(PortfolioSnapshot.model_validate(snapshot),RiskPolicy(revision=0),now).model_dump_json())
    @asynccontextmanager
    async def connection(*args,**kwargs):
        agent.mcp.capabilities['fixture']=SimpleNamespace(calls=1)
        yield SimpleNamespace(token='fixture',tools=None,portfolio_snapshot=AsyncMock(return_value=snapshot),_snapshot=AsyncMock(return_value=snapshot))
    monkeypatch.setattr(agent.mcp,'connection',connection)
    monkeypatch.setattr(agent,'status',lambda:{'configured':True})
    async def scenario():
        request=asyncio.create_task(agent.portfolio_chat(1,PortfolioChatRequest(message='fixture')))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set(): await asyncio.sleep(.001)
            if interruption=='cancel':
                request.cancel()
                with pytest.raises(asyncio.CancelledError): await request
            else:
                from fastapi import HTTPException
                with pytest.raises(HTTPException) as error: await request
                assert error.value.status_code==504
            assert 1 in agent.active
        finally:
            release.set()
            await asyncio.gather(*agent.workers.get(1,()),return_exceptions=True)
            await asyncio.sleep(0)
        assert 1 not in agent.active
        with original_connect() as db:
            assert db.execute('SELECT COUNT(*) FROM option_chat_turns').fetchone()[0]==0
            assert db.execute('SELECT COUNT(*) FROM option_chat_conversations').fetchone()[0]==0
            assert db.execute('SELECT COUNT(*) FROM portfolio_risk_reports').fetchone()[0]==0
            assert db.execute("SELECT COUNT(*) FROM option_agent_runs WHERE status='completed'").fetchone()[0]==0
            assert db.execute("SELECT COUNT(*) FROM audit WHERE event='OPTIONS_CHAT_COMPLETED'").fetchone()[0]==0
    asyncio.run(scenario())
