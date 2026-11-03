from contextlib import contextmanager
import sqlite3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.terminal.options_platform_store import OptionsPlatformStore, PlatformConflictError
from app.terminal.routers.options_platform import options_platform_router
from test_options_strategies import fixture, NOW
from app.terminal.options_strategies import analyze_strategy

class DB:
    def __init__(self,path): self.path=path
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path)
        try:
            with db: yield db
        finally: db.close()

def agent_stub():
    from types import SimpleNamespace
    from threading import Lock,RLock
    from app.terminal.options_agent import OptionsAgent
    a=object.__new__(OptionsAgent);a.guard=Lock();a.refresh_active=set();a.active=set();a.refresh_last={};a.workers={}
    a.mcp=SimpleNamespace(pending={});a.market=SimpleNamespace(lock=RLock(),session_generation=lambda owner:'g');a.store=None;a.deadline_seconds=2
    return a

def test_owner_scope_immutable_baseline(tmp_path):
    store=OptionsPlatformStore(DB(tmp_path/'test.db'))
    req,ev=fixture(); report=analyze_strategy(req,ev,None,NOW)
    store.save_market_evidence(7,ev); store.save_report(7,'analysis',report)
    assert store.get_market_evidence(8,ev.evidence_id) is None
    assert store.get_report(8,'analysis',report.report_id) is None
    with pytest.raises(PlatformConflictError): store.save_market_evidence(8,ev)
    baseline=store.save_baseline(7,report.report_id,'Original')
    assert store.get_baseline(7,baseline.baseline_id).analysis_id==report.report_id
    assert store.get_baseline(8,baseline.baseline_id) is None
    assert store.list_reports(7,'analysis',limit=1,offset=0)==[report]
    with pytest.raises(ValueError): store.get_market_evidence(None,ev.evidence_id)

def test_authentication_and_public_forgery_rejected(tmp_path):
    app=FastAPI();app.include_router(options_platform_router)
    app.state.options_platform_store=OptionsPlatformStore(DB(tmp_path/'api.db'))
    from app.terminal.options_platform_service import OptionsPlatformService
    app.state.options_platform_service=OptionsPlatformService(agent_stub(),app.state.options_platform_store)
    client=TestClient(app)
    assert client.get('/api/options-platform/capabilities').status_code==401
    app=FastAPI();app.include_router(options_platform_router)
    app.state.options_platform_store=OptionsPlatformStore(DB(tmp_path/'api.db'))
    app.state.options_platform_service=OptionsPlatformService(agent_stub(),app.state.options_platform_store)
    @app.middleware('http')
    async def owner(request,call_next):
        request.state.user={'id':7}; return await call_next(request)
    client=TestClient(app)
    req,ev=fixture()
    assert client.post('/api/options-platform/analyses',json=req.model_dump(mode='json')).status_code==404
    payload=req.model_dump(mode='json');payload['evidence']=ev.model_dump(mode='json')
    assert client.post('/api/options-platform/analyses',json=payload).status_code==422

def test_authenticated_analysis_history_and_baselines(tmp_path):
    from app.terminal.options_platform_service import OptionsPlatformService
    from datetime import UTC,datetime
    app=FastAPI();app.include_router(options_platform_router)
    store=OptionsPlatformStore(DB(tmp_path/'api.db'))
    app.state.options_platform_store=store
    app.state.options_platform_service=OptionsPlatformService(agent_stub(),store)
    @app.middleware('http')
    async def owner(request,call_next):
        request.state.user={'id':int(request.headers.get('Owner','7'))};return await call_next(request)
    client=TestClient(app);req,ev=fixture();store.save_market_evidence(7,ev)
    res=client.post('/api/options-platform/analyses',json=req.model_dump(mode='json'))
    assert res.status_code==200;report=res.json();id=report['report_id']
    assert client.get('/api/options-platform/analyses/'+id).json()==report
    assert client.get('/api/options-platform/analyses?limit=1').json()==[report]
    assert client.get('/api/options-platform/analyses/'+id,headers={'Owner':'8'}).status_code==404
    assert client.get('/api/options-platform/analyses',headers={'Owner':'8'}).json()==[]
    assert client.post('/api/options-platform/analyses',json=req.model_dump(mode='json'),headers={'Owner':'8'}).status_code==404
    baseline=client.post('/api/options-platform/baselines',json={'analysis_id':id,'name':'Snapshot'}).json()
    assert baseline['analysis_id']==id
    assert client.get('/api/options-platform/baselines/'+baseline['baseline_id']).json()==baseline
    assert client.get('/api/options-platform/baselines').json()==[baseline]
    assert client.get('/api/options-platform/baselines/'+baseline['baseline_id'],headers={'Owner':'8'}).status_code==404
    assert client.get('/api/options-platform/analyses?limit=101').status_code==422

def test_store_busy_and_immutable_content(tmp_path):
    from app.terminal.options_platform_store import PlatformStoreBusyError
    store=OptionsPlatformStore(DB(tmp_path/'busy.db'));req,ev=fixture();store.save_market_evidence(7,ev)
    with pytest.raises(PlatformConflictError):
        store.save_market_evidence(7,ev.model_copy(update={'source':'different'}))
    db=sqlite3.connect(tmp_path/'busy.db');db.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(PlatformStoreBusyError):store.save_market_evidence(7,ev)
    finally:db.rollback();db.close()
    with store.store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute("DELETE FROM options_platform_artifacts")

def test_publication_check_rolls_back_before_commit(tmp_path):
    store=OptionsPlatformStore(DB(tmp_path/'fenced.db'));req,ev=fixture();checks=[]
    def check():
        checks.append(True)
        if len(checks)==2:raise TimeoutError()
    with pytest.raises(TimeoutError):store.save_market_evidence(7,ev,_check=check)
    assert store.get_market_evidence(7,ev.evidence_id) is None

def test_market_canonical_order_is_idempotent(tmp_path):
    store=OptionsPlatformStore(DB(tmp_path/'canonical.db'));_,ev=fixture()
    store.save_market_evidence(7,ev)
    store.save_market_evidence(7,ev.model_copy(update={'contracts':tuple(reversed(ev.contracts)),'quotes':tuple(reversed(ev.quotes))}))

@pytest.mark.parametrize('timeout',[False,True])
def test_market_worker_cancel_keeps_shared_admission(tmp_path,monkeypatch,timeout):
    import asyncio
    from threading import Event,Lock,RLock
    from types import SimpleNamespace
    from app.terminal.options_agent import OptionsAgent
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.options_snapshot import OptionsContext
    from fastapi import HTTPException
    req,ev=fixture();entered=Event();release=Event()
    def acquire(*args,**kwargs):
        assert kwargs['deadline'] is not None
        entered.set();release.wait(3);return ev
    monkeypatch.setattr('app.terminal.options_platform_service.fetch_strategy_market_evidence',acquire)
    a=object.__new__(OptionsAgent);a.guard=Lock();a.refresh_active=set();a.active=set();a.refresh_last={};a.workers={}
    a.mcp=SimpleNamespace(pending={});a.market=SimpleNamespace(lock=RLock(),session_generation=lambda owner:'g');a.store=None;a.deadline_seconds=2
    if timeout:a.deadline_seconds=.05
    store=OptionsPlatformStore(DB(tmp_path/'cancel.db'));service=OptionsPlatformService(a,store)
    async def run():
        task=asyncio.create_task(service.market_snapshot(7,OptionsContext()))
        for _ in range(100):
            if entered.is_set():break
            await asyncio.sleep(.005)
        assert entered.is_set()
        if timeout:
            with pytest.raises(HTTPException) as error:await task
            assert error.value.status_code==504
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        assert 7 in a.refresh_active
        with pytest.raises(HTTPException) as error:await service.market_snapshot(7,OptionsContext())
        assert error.value.status_code==409
        release.set()
        pending=tuple(a.workers.get(7,()))
        await asyncio.gather(*pending,return_exceptions=True);await asyncio.sleep(0)
        assert 7 not in a.refresh_active
        assert store.get_market_evidence(7,ev.evidence_id) is None
    asyncio.run(run())

def test_market_snapshot_server_fetch_owner_and_generation_fence(tmp_path,monkeypatch):
    import asyncio
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.options_snapshot import OptionsContext
    from fastapi import HTTPException
    req,ev=fixture();a=agent_stub();calls=[]
    def fetch(market,store,owner,context,deadline=None):
        calls.append((owner,context,deadline));return ev
    monkeypatch.setattr('app.terminal.options_platform_service.fetch_strategy_market_evidence',fetch)
    store=OptionsPlatformStore(DB(tmp_path/'market.db'));service=OptionsPlatformService(a,store)
    result=asyncio.run(service.market_snapshot(7,OptionsContext()))
    assert result==ev and calls[0][0]==7 and calls[0][2] is not None
    assert store.get_market_evidence(7,ev.evidence_id).canonical_json()==ev.canonical_json()
    assert store.get_market_evidence(8,ev.evidence_id) is None
    a.refresh_last.clear();generation=['g']
    a.market.session_generation=lambda owner:generation[0]
    def changed(*args,**kwargs):generation[0]='changed';return ev.model_copy(update={'evidence_id':__import__('uuid').uuid4()})
    monkeypatch.setattr('app.terminal.options_platform_service.fetch_strategy_market_evidence',changed)
    with pytest.raises(HTTPException) as error:asyncio.run(service.market_snapshot(7,OptionsContext()))
    assert error.value.status_code==503
    assert len(store.list_market_evidence(7))==1

@pytest.mark.parametrize('method,path,body',[
    ('get','/capabilities',None),('post','/market-snapshot',{}),
    ('get','/analyses',None),('get','/baselines',None),
    ('get','/analyses/00000000-0000-0000-0000-000000000001',None),
    ('get','/baselines/00000000-0000-0000-0000-000000000001',None),
    ('post','/baselines',{'analysis_id':'00000000-0000-0000-0000-000000000001','name':'A'})])
def test_all_routes_require_individual_owner(method,path,body,tmp_path):
    app=FastAPI();app.include_router(options_platform_router)
    app.state.options_platform_store=OptionsPlatformStore(DB(tmp_path/'auth.db'))
    client=TestClient(app)
    response=client.request(method,'/api/options-platform'+path,**({'json':body} if body is not None else {}))
    assert response.status_code==401

def test_hypothetical_calc_and_storage_run_offloop(tmp_path,monkeypatch):
    import asyncio,threading
    from app.terminal.options_platform_service import OptionsPlatformService
    store=OptionsPlatformStore(DB(tmp_path/'offloop.db'));req,ev=fixture();store.save_market_evidence(7,ev)
    main=threading.get_ident();original=store.get_market_evidence;seen=[]
    def get(*args):
        seen.append(threading.get_ident());assert threading.get_ident()!=main;return original(*args)
    monkeypatch.setattr(store,'get_market_evidence',get)
    result=asyncio.run(OptionsPlatformService(agent_stub(),store).analyze(7,req))
    assert result.request==req and len(seen)==2

def test_owned_analysis_uses_server_portfolio_available_proof(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from datetime import UTC,datetime
    from app.terminal.options_market_contracts import StrategyMarketEvidence
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.portfolio_contracts import PortfolioSnapshot,PortfolioSection,PortfolioRow
    req,ev=fixture(mode='owned',holding_row_id='h',acquisition_cost_per_share='20')
    raw=ev.model_dump();raw['contracts'][0]['instrument_id']='nse_cm|1';raw['quotes'][0]['contract_id']='nse_cm|1'
    ev=StrategyMarketEvidence(**raw);req=req.model_copy(update={'stock_contract_id':'nse_cm|1'})
    snapshot=PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW,
        sections={'holdings':PortfolioSection(state='available',rows=[PortfolioRow(row_id='h',exchange='nse_cm',token='1',
            underlying_key='stock',identity_verified=True,currency='INR',inventory_coverage='disjoint',
            inventory_coverage_basis='verified broker inventory',quantity='500',available_quantity='100',average_price='80')])})
    calls=[]
    def fetch(owner,**kwargs):calls.append((owner,kwargs));return snapshot
    a=agent_stub();a.mcp.portfolio_service=SimpleNamespace(fetch=fetch,assert_generation=lambda *args,**kwargs:None)
    store=OptionsPlatformStore(DB(tmp_path/'owned.db'));store.save_market_evidence(7,ev)
    report=asyncio.run(OptionsPlatformService(a,store).analyze(7,req))
    assert report.acquisition_basis.stock_basis==80
    assert report.current_basis.stock_basis==100
    assert report.holding_evidence[0].available_quantity==100
    assert report.holding_evidence[0].evidence_id==snapshot.evidence_id
    assert calls[0][0]==7 and calls[0][1]['force'] is True and calls[0][1]['deadline_monotonic'] is not None
    a.refresh_last.clear();snapshot.sections['holdings'].rows[0].available_quantity=__import__('decimal').Decimal(99)
    report=asyncio.run(OptionsPlatformService(a,store).analyze(7,req))
    assert 'holding_shortfall' in report.reasons
