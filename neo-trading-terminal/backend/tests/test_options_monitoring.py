from decimal import Decimal
import pytest
from test_options_strategies import fixture, NOW
from test_options_platform_api import DB
from app.terminal.options_strategies import analyze_strategy, _metrics
from app.terminal.options_platform_store import OptionsPlatformStore

def test_zero_payoff_regions():
    d=Decimal
    cap=_metrics(1,d(100),d(100),d(0),None,d(0),d(0),None,'test')
    assert cap.zero_profit_regions==((d(100),None),)
    floor=_metrics(1,d(90),d(110),d(0),d(90),d(0),d(0),None,'test')
    assert floor.zero_profit_regions==((d(0),d(90)),)
    flat=_metrics(1,d(100),d(100),d(0),d(100),d(0),d(0),None,'test')
    assert flat.zero_profit_regions==((d(0),None),)

def test_report_exact_selection_and_holding_references(tmp_path):
    store=OptionsPlatformStore(DB(tmp_path/'db'));req,ev=fixture();r=analyze_strategy(req,ev,None,NOW)
    store.save_market_evidence(7,ev)
    for legs in ((),r.selected_legs[::-1],ev.contracts):
        with pytest.raises(ValueError): store.save_report(7,'analysis',r.model_copy(update={'selected_legs':legs}))
    from app.terminal.options_strategy_contracts import HoldingEvidence
    from uuid import uuid4
    h=HoldingEvidence(row_id='h',stock_contract_id='stock',observed_at=NOW,evidence_id=uuid4())
    with pytest.raises(ValueError): store.save_report(7,'analysis',r.model_copy(update={'holding_evidence':(h,)}))

def test_unitized_external_flows_and_missing_data():
    from app.terminal.options_platform_risk import EquityObservation, unitized_drawdown
    from datetime import timedelta
    def point(i,e,flow='0',**kw):
        return EquityObservation(observed_at=NOW+timedelta(days=i),sequence=i,equity_inr=e,external_flow_inr=flow,**kw)
    assert unitized_drawdown((point(0,'100'),point(1,'200','100'),point(2,'180')))==Decimal('10')
    assert unitized_drawdown((point(0,'100'),point(1,'50','-50')))==0
    assert unitized_drawdown((point(0,'100'),point(2,'80'))) is None
    assert unitized_drawdown((point(0,'100'),point(1,'80',flow_timing='unknown'))) is None
    assert unitized_drawdown((point(0,'0'),point(1,'100'))) is None

def test_policy_revision_zero_and_monitor_claims(tmp_path):
    from app.terminal.options_platform_risk import PlatformRiskPolicy, MonitoringSettings
    from app.terminal.options_platform_store import PlatformConflictError
    s=OptionsPlatformStore(DB(tmp_path/'db'))
    assert s.get_risk_policy(7).capital_cap_inr is None
    p=s.put_risk_policy(7,PlatformRiskPolicy(revision=0,capital_cap_inr='0'))
    assert p.revision==1 and p.capital_cap_inr==0
    with pytest.raises(PlatformConflictError): s.put_risk_policy(7,PlatformRiskPolicy())
    assert s.get_risk_policy(8).revision==0
    s.put_monitoring(7,MonitoringSettings(enabled=True),now=100)
    assert s.claim_monitor(7,'g',now=99) is None
    c=s.claim_monitor(7,'g',now=100)
    assert c and s.claim_monitor(7,'g',now=101) is None
    assert s.claim_monitor(7,'g',now=161) is not None

def test_alert_transitions_owner_and_lease_fencing(tmp_path):
    from app.terminal.options_platform_risk import MonitoringSettings
    s=OptionsPlatformStore(DB(tmp_path/'db'));s.put_monitoring(7,MonitoringSettings(enabled=True),now=0)
    claim=s.claim_monitor(7,'g',now=0)
    assert s.finish_monitor(7,claim,{'cap':'breach'},now=1)
    assert len(s.list_alerts(7))==1 and s.list_alerts(8)==[]
    claim=s.claim_monitor(7,'g',now=61);s.finish_monitor(7,claim,{'cap':'breach'},now=62)
    assert len(s.list_alerts(7))==1
    claim=s.claim_monitor(7,'g',now=122);s.finish_monitor(7,claim,{'cap':'cannot_assess'},now=123)
    assert s.list_alerts(7)[0]['kind']=='data_quality'
    assert not s.finish_monitor(7,claim,{'cap':'pass'},now=124)
    alert=s.list_alerts(7)[0]
    assert s.mark_alert(8,alert['id'],'read',now=125) is None
    assert s.mark_alert(7,alert['id'],'acknowledge',now=125)['acknowledged_at']==125

def test_documented_fill_mapping_no_symbol_inference():
    from app.terminal.options_monitoring import normalize_trade_report
    raw={'stat':'ok','stCode':200,'data':[{'flId':'f','exSeg':'nse_cm','tok':'123','fldQty':2,'avgPrc':'0','trnsTp':'B','exTm':'01-Nov-2026 10:00:00','rptTp':'fill'}]}
    mapped=normalize_trade_report(raw)
    assert mapped['fills'][0]['contract_id']=='nse_cm|123'
    assert mapped['fills'][0]['price']=='0'
    raw['data'][0]['tok']=''
    assert normalize_trade_report(raw)['fills']==[]
    assert normalize_trade_report({'data':[{'symbol':'ABC','qty':2}]})['status']=='unavailable'

def test_risk_policy_disabled_zero_and_hostile_context():
    from app.terminal.options_platform_risk import PlatformRiskPolicy,evaluate_platform_risk,EquityObservation
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    from decimal import localcontext,Inexact,ROUND_DOWN
    from datetime import timedelta
    snap=PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW)
    equity=(EquityObservation(observed_at=NOW,sequence=0,equity_inr='3'),EquityObservation(observed_at=NOW+timedelta(days=1),sequence=1,equity_inr='2'))
    with localcontext() as ctx:
        ctx.prec=2;ctx.rounding=ROUND_DOWN;ctx.traps[Inexact]=True
        r=evaluate_platform_risk(PlatformRiskPolicy(drawdown_maxpercent='0'),snap,equity=equity,as_of=NOW+timedelta(days=1))
    assert r['checks'][-1]['outcome']=='breach'
    assert r['checks'][1]['outcome']=='cannot_assess'

def test_background_admission_interactive_priority(tmp_path):
    import asyncio
    asyncio.run(_background_priority(tmp_path))

async def _background_priority(tmp_path):
    from app.terminal.options_platform_service import OptionsPlatformService
    from test_options_platform_api import agent_stub
    from fastapi import HTTPException
    a=agent_stub();s=OptionsPlatformService(a,OptionsPlatformStore(DB(tmp_path/'db')))
    a.active.add(9)
    with pytest.raises(HTTPException): await s._admitted(7,lambda d,c:42,background=True)
    a.active.clear();a.refresh_active.update((8,9))
    with pytest.raises(HTTPException): await s._admitted(7,lambda d,c:42,background=True)
    a.refresh_active.clear()
    assert await s._admitted(7,lambda d,c:42,background=True)==42

def test_monitor_api_owner_private_policy_equity_alerts(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.terminal.routers.options_platform import options_platform_router
    app=FastAPI();app.include_router(options_platform_router)
    app.state.options_platform_store=OptionsPlatformStore(DB(tmp_path/'db'))
    client=TestClient(app)
    assert client.get('/api/options-platform/risk-policy').status_code==401
    app=FastAPI();app.include_router(options_platform_router)
    app.state.options_platform_store=OptionsPlatformStore(DB(tmp_path/'db'))
    @app.middleware('http')
    async def owner(request,call_next):
        request.state.user={'id':int(request.headers.get('Owner','7'))};return await call_next(request)
    client=TestClient(app)
    assert client.get('/api/options-platform/risk-policy').json()['revision']==0
    assert client.put('/api/options-platform/risk-policy',json={'revision':0,'capital_cap_inr':'0'}).json()['revision']==1
    assert client.put('/api/options-platform/risk-policy',json={'revision':0}).status_code==409
    assert client.get('/api/options-platform/risk-policy',headers={'Owner':'8'}).json()['revision']==0
    assert client.put('/api/options-platform/monitoring',json={'enabled':True,'interval_seconds':1}).status_code==422
    assert client.put('/api/options-platform/monitoring',json={'enabled':True}).json()['status']=='pending'
    body={'observations':[{'sequence':0,'equity_inr':'100','observed_at':NOW.isoformat()}]}
    assert client.post('/api/options-platform/equity-imports',json=body).status_code==200
    assert len(client.get('/api/options-platform/equity-imports').json())==1
    assert client.get('/api/options-platform/equity-imports',headers={'Owner':'8'}).json()==[]
    assert client.get('/api/options-platform/alerts?limit=101').status_code==422

def test_claim_concurrency_restart_and_skip_missed_ticks(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.terminal.options_platform_risk import MonitoringSettings
    db=DB(tmp_path/'db');s=OptionsPlatformStore(db)
    s.put_monitoring(7,MonitoringSettings(enabled=True),now=100)
    with ThreadPoolExecutor(4) as pool: results=list(pool.map(lambda _:s.claim_monitor(7,'g',now=100),range(4)))
    assert sum(r is not None for r in results)==1
    old=next(r for r in results if r)
    restarted=OptionsPlatformStore(db)
    assert restarted.claim_monitor(7,'g',now=159) is None
    claim=restarted.claim_monitor(7,'g',now=1000)
    assert not restarted.finish_monitor(7,old,{'a':'breach'},now=1000)
    assert restarted.finish_monitor(7,claim,{'a':'breach'},now=1001)
    assert restarted.get_monitoring(7)['next_due']==1061
    assert len(restarted.list_alerts(7))==1

def test_pnl_known_costs_and_explicit_association_validation(tmp_path):
    from app.terminal.options_monitoring import OptionsMonitoringService,association_pnl
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.options_platform_risk import AssociationRequest
    from app.terminal.portfolio_contracts import PortfolioSnapshot,PortfolioSection,PortfolioRow
    from test_options_platform_api import agent_stub
    from types import SimpleNamespace
    req,ev=fixture();report=analyze_strategy(req,ev,None,NOW)
    # Canonical report IDs use exchange|token; no symbol association.
    raw=ev.model_dump();raw['contracts'][0]['instrument_id']='nse_cm|s';raw['contracts'][1]['instrument_id']='nse_fo|c';raw['quotes'][0]['contract_id']='nse_cm|s';raw['quotes'][1]['contract_id']='nse_fo|c'
    from app.terminal.options_market_contracts import StrategyMarketEvidence
    ev=StrategyMarketEvidence(**raw);req=req.model_copy(update={'stock_contract_id':'nse_cm|s','call_contract_id':'nse_fo|c'})
    report=analyze_strategy(req,ev,None,NOW)
    rows=[PortfolioRow(row_id=id,exchange=exchange,token=token,quantity=q,last_price=price,identity_verified=True,currency='INR',inventory_coverage='disjoint',inventory_coverage_basis='fixture') for id,exchange,token,q,price in [('s','nse_cm','s','100','105'),('c','nse_fo','c','-100','3')]]
    fills=[dict(fill_id='fs',contract_id='nse_cm|s',quantity='100',price='100',side='BUY'),dict(fill_id='fc',contract_id='nse_fo|c',quantity='100',price='5',side='SELL')]
    assert association_pnl(report,rows,fills,costs_inr=Decimal(10))['comparison_after_declared_costs_inr']=='690'
    assert association_pnl(report,rows+rows[:1],fills,costs_inr=Decimal(10))['status']=='cannot_assess'
    assert association_pnl(report,[rows[0].model_copy(update={'identity_verified':False}),rows[1]],fills,costs_inr=Decimal(10))['status']=='cannot_assess'
    assert association_pnl(report,rows,fills)['unrealized_inr'] is None
    store=OptionsPlatformStore(DB(tmp_path/'db'));store.save_market_evidence(7,ev);store.save_report(7,'analysis',report);baseline=store.save_baseline(7,report.report_id,'A')
    snap=PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW,sections={'positions':PortfolioSection(state='available',rows=rows)})
    a=agent_stub();a.market.get_session=lambda owner:SimpleNamespace(generation='g',source='kotak',broker=SimpleNamespace(is_authenticated=True))
    service=OptionsMonitoringService(OptionsPlatformService(a,store),clock=lambda:NOW.timestamp())
    store.save_private_record(7,'portfolio',dict(snapshot=snap.model_dump(mode='json'),fills={'fills':fills},generation='g'),now=0)
    body=AssociationRequest(portfolio_evidence_id=snap.evidence_id,row_ids=('s','c'),fill_ids=('fs','fc'),confirm_executed=True,costs_inr='10')
    result=service.associate(7,baseline.baseline_id,body)
    assert result['executed_confirmed'] is False and result['baseline_mode']=='hypothetical'
    assert result['execution_confirmation_status']=='cannot_assess'
    assert result['pnl']['comparison_after_declared_costs_inr']=='690'
    assert result['pnl']['realized_inr'] is None and result['pnl']['unrealized_inr'] is None
    from app.terminal.options_lot_ledger import LotLedgerImport
    ledger=LotLedgerImport(coverage_start=NOW,coverage_end=NOW,opening_inventory=[dict(contract_id=id,quantity=0) for id in ('nse_cm|s','nse_fo|c')],trades=[dict(f,sequence=i,quantity=100,costs_inr='5',executed_at=NOW) for i,f in enumerate(fills)])
    saved=store.import_lot_ledger(7,ledger,now=0)
    linked=service.associate(7,baseline.baseline_id,body.model_copy(update={'lot_ledger_id':saved['id'],'costs_inr':None}))
    assert linked['executed_confirmed'] is True and linked['execution_source']=='user_declared'
    assert linked['pnl']['status']=='assessed' and Decimal(linked['pnl']['unrealized_inr'])==690
    assert linked['current_coverage_verified'] is True
    with pytest.raises(KeyError):service.associate(8,baseline.baseline_id,body)
    with pytest.raises(ValueError):service.associate(7,baseline.baseline_id,body.model_copy(update={'row_ids':('s',)}))
    a.market.get_session=lambda owner:SimpleNamespace(generation='new',source='kotak',broker=SimpleNamespace(is_authenticated=True))
    with pytest.raises(ValueError):service.associate(7,baseline.baseline_id,body)
    generations=iter(('g','new'))
    service._session=lambda owner:next(generations)
    with pytest.raises(ValueError):service.associate(7,baseline.baseline_id,body)

def test_monitor_fake_clock_suspend_reconnect_and_one_tick(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from test_options_platform_api import agent_stub
    from app.terminal.options_monitoring import OptionsMonitoringService
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.options_platform_risk import MonitoringSettings
    async def run():
        a=agent_stub();session=SimpleNamespace(generation='g',source='demo',broker=SimpleNamespace(is_authenticated=False))
        a.market.get_session=lambda owner:session
        s=OptionsPlatformStore(DB(tmp_path/'db'));clock=[0];m=OptionsMonitoringService(OptionsPlatformService(a,s),clock=lambda:clock[0])
        s.put_monitoring(7,MonitoringSettings(enabled=True),now=0)
        await m.run_due();assert s.get_monitoring(7)['status']=='suspended'
        session.source='kotak';session.broker.is_authenticated=True;session.generation='new'
        await m.run_due();assert s.get_monitoring(7)['next_due']==60
        calls=[];gate=asyncio.Event()
        async def tick(owner,claim):calls.append((owner,claim));await gate.wait()
        m._tick=tick;clock[0]=60
        await m.run_due();await asyncio.sleep(0);assert len(calls)==1
        clock[0]=1000;await m.run_due();assert len(calls)==1
        gate.set();await asyncio.gather(*m.ticks.values());await asyncio.sleep(0)
        assert calls[0][1]['generation']=='new'
    asyncio.run(run())

def test_background_cancel_retains_actual_capacity_and_no_late_alert(tmp_path):
    import asyncio
    from threading import Event
    from test_options_platform_api import agent_stub
    from app.terminal.options_platform_service import OptionsPlatformService
    from fastapi import HTTPException
    async def run():
        a=agent_stub();s=OptionsPlatformStore(DB(tmp_path/'db'));p=OptionsPlatformService(a,s)
        entered=Event();release=Event()
        def blocked(deadline,check):
            entered.set();release.wait(3);check();raise AssertionError('late publication')
        task=asyncio.create_task(p._admitted(7,blocked,background=True))
        await asyncio.to_thread(entered.wait,1);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert 7 in a.refresh_active
        with pytest.raises(HTTPException):await p._admitted(7,lambda d,c:None,background=True)
        release.set();await asyncio.gather(*tuple(a.workers.get(7,())),return_exceptions=True);await asyncio.sleep(0)
        assert 7 not in a.refresh_active and s.list_alerts(7)==[]
    asyncio.run(run())

def test_unavailable_after_assessed_does_not_claim_recovery(tmp_path):
    from app.terminal.options_platform_risk import MonitoringSettings
    s=OptionsPlatformStore(DB(tmp_path/'db'));s.put_monitoring(7,MonitoringSettings(enabled=True),now=0)
    c=s.claim_monitor(7,'g',now=0);s.finish_monitor(7,c,{'x':'breach'},now=1)
    c=s.claim_monitor(7,'g',now=61);s.finish_monitor(7,c,{'x':'cannot_assess'},now=62)
    c=s.claim_monitor(7,'g',now=122);s.finish_monitor(7,c,{'x':'pass'},now=123)
    assert len(s.list_alerts(7))==2
    assert all(x['kind']!='recovery' for x in s.list_alerts(7))

def test_heavy_global_one_and_queue_bound(tmp_path):
    from app.terminal.options_platform_store import PlatformConflictError
    s=OptionsPlatformStore(DB(tmp_path/'db'))
    for i in range(20):s.enqueue_heavy(i+1,'scan',now=i)
    with pytest.raises(PlatformConflictError):s.enqueue_heavy(50,'backtest',now=50)
    claim=s.claim_heavy(now=50)
    assert claim['owner']==1 and s.claim_heavy(now=500) is None
    assert not s.finish_heavy(2,claim['id'],claim['token'])
    assert s.finish_heavy(1,claim['id'],claim['token'])
    assert s.claim_heavy(now=501)['owner']==2


def test_unconfirmed_hypothetical_is_not_account_risk():
    from app.terminal.options_platform_risk import PlatformRiskPolicy,evaluate_platform_risk
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    req,ev=fixture();report=analyze_strategy(req,ev,None,NOW)
    snap=PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW)
    result=evaluate_platform_risk(PlatformRiskPolicy(capital_cap_inr='0',observation_max_age_seconds=60),snap,[report],[dict(baseline_analysis_id=str(report.report_id),executed_confirmed=False)],as_of=NOW)
    assert next(c for c in result['checks'] if c['key']=='capital')['outcome']=='cannot_assess'


def test_pnl_rejects_duplicate_inventory_and_unverified_marks():
    from app.terminal.options_monitoring import association_pnl
    from app.terminal.portfolio_contracts import PortfolioRow
    req,ev=fixture();report=analyze_strategy(req,ev,None,NOW)
    rows=[PortfolioRow(row_id='s',exchange='x',token='s',quantity=100,last_price=105)]
    fills=[dict(contract_id='x|s',side='BUY',quantity='100',price='100')]
    assert association_pnl(report,rows+rows,fills,costs_inr=Decimal(0))['status']=='cannot_assess'


def test_private_publication_rollback_and_immutable_associations(tmp_path):
    import sqlite3
    s=OptionsPlatformStore(DB(tmp_path/'db'))
    def cancelled():raise TimeoutError()
    with pytest.raises(TimeoutError):s.save_private_record(7,'portfolio',{'x':1},now=0,_check=cancelled)
    assert s.list_private_records(7,'portfolio')==[]
    record=s.save_private_record(7,'association',{'baseline_id':'a'},now=0)
    with pytest.raises(sqlite3.IntegrityError):
        with s._db() as db:db.execute('UPDATE platform_records SET payload=? WHERE id=?',('{}',record['id']))


def test_future_equity_cannot_establish_drawdown():
    from datetime import timedelta
    from app.terminal.options_platform_risk import PlatformRiskPolicy,EquityObservation,evaluate_platform_risk
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    snap=PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW)
    observations=(EquityObservation(sequence=0,equity_inr='100',observed_at=NOW),EquityObservation(sequence=1,equity_inr='50',observed_at=NOW+timedelta(days=1)))
    result=evaluate_platform_risk(PlatformRiskPolicy(drawdown_maxpercent='0'),snap,equity=observations,as_of=NOW)
    assert result['checks'][-1]['outcome']=='cannot_assess'


def test_actual_tick_publishes_with_fake_clock_and_lifecycle(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from app.terminal.options_monitoring import OptionsMonitoringService
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.options_platform_risk import MonitoringSettings,PlatformRiskPolicy
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    from test_options_platform_api import agent_stub
    async def run():
        a=agent_stub();s=OptionsPlatformStore(DB(tmp_path/'db'))
        a.market.get_session=lambda owner:SimpleNamespace(generation='g',source='kotak',broker=SimpleNamespace(is_authenticated=True))
        snapshot=PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW)
        a.mcp.portfolio_service=SimpleNamespace(fetch=lambda *a,**k:snapshot,assert_generation=lambda *a,**k:None,_acquire=lambda lock,deadline:lock.acquire())
        m=OptionsMonitoringService(OptionsPlatformService(a,s),clock=lambda:NOW.timestamp()+120)
        s.put_risk_policy(7,PlatformRiskPolicy(observation_max_age_seconds=60))
        s.put_monitoring(7,MonitoringSettings(enabled=True),now=NOW.timestamp())
        claim=s.claim_monitor(7,'g',now=NOW.timestamp())
        await m._tick(7,claim)
        reports=s.list_private_records(7,'risk')
        assert len(reports)==1 and reports[0]['checks'][0]['value']=='120.0'
        assert len(s.list_alerts(7))==1
        await m.start();assert m.running and m.task is not None
        await m.stop();assert not m.running and m.task is None
    asyncio.run(run())


def test_functional_trade_acquisition_owner_worker_and_generation_fence(tmp_path):
    import asyncio
    from threading import get_ident
    from types import SimpleNamespace
    from app.terminal.options_monitoring import OptionsMonitoringService
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    from test_options_platform_api import agent_stub
    async def run():
        a=agent_stub();s=OptionsPlatformStore(DB(tmp_path/'db'));main=get_ident();calls=[]
        a.market.get_session=lambda owner:SimpleNamespace(generation='g',source='kotak',broker=SimpleNamespace(is_authenticated=True))
        snapshot=PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW)
        a.mcp.portfolio_service=SimpleNamespace(fetch=lambda *a,**k:snapshot,assert_generation=lambda *a,**k:None,_acquire=lambda lock,deadline:lock.acquire())
        def call(method,**kw):
            calls.append((method,kw,get_ident()))
            return {'stat':'ok','stCode':200,'data':[dict(flId='f',tok='123',exSeg='nse_cm',trnsTp='B',fldQty=100,avgPrc='0',exTm='01-Nov-2026 10:00:00',rptTp='fill')]}
        a.market.call=call;m=OptionsMonitoringService(OptionsPlatformService(a,s))
        result=await m.acquire_association_evidence(7)
        assert result['fills']['fills'][0]['price']=='0'
        assert calls[0][0]=='trade_report' and calls[0][1]['user_id']==7 and calls[0][2]!=main
        assert s.list_private_records(8,'portfolio')==[]
        a.refresh_last.clear()
        def changed(*a,**k):raise ValueError('generation changed')
        a.mcp.portfolio_service.assert_generation=changed
        with pytest.raises(ValueError):await m.acquire_association_evidence(7)
        assert len(s.list_private_records(7,'portfolio'))==1
    asyncio.run(run())


@pytest.mark.parametrize('age',[None,60])
def test_age_null_is_independent_and_missing_confirmed_coverage_stays_unavailable(tmp_path,age):
    from app.terminal.options_platform_risk import PlatformRiskPolicy,evaluate_platform_risk,MonitoringSettings
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    from uuid import uuid4
    req,ev=fixture();one=analyze_strategy(req,ev,None,NOW)
    two=one.model_copy(update={'report_id':uuid4()})
    snapshot=PortfolioSnapshot(retrieval_started_at=NOW,retrieval_finished_at=NOW,source_observed_at=NOW)
    policy=PlatformRiskPolicy(capital_cap_inr=str(one.current_capital*Decimal('1.5')),strategy_maxloss_inr='0',observation_max_age_seconds=age)
    associations=[dict(baseline_analysis_id=str(r.report_id),executed_confirmed=True,current_coverage_verified=True) for r in (one,two)]
    first=evaluate_platform_risk(policy,snapshot,[one,two],associations,as_of=NOW)
    states=lambda report:{c['key']:c['outcome'] for c in report['checks'] if c['limit'] is not None}
    assert states(first)['capital']=='breach'
    assert states(first)['strategy_loss:'+str(two.report_id)]=='breach'
    associations[1]['current_coverage_verified']=False
    missing=evaluate_platform_risk(policy,snapshot,[one,two],associations,as_of=NOW)
    assert states(missing)['capital']=='cannot_assess'
    assert states(missing)['strategy_loss:'+str(two.report_id)]=='cannot_assess'
    missing_report=evaluate_platform_risk(policy,snapshot,[one],associations,as_of=NOW)
    assert states(missing_report)['strategy_loss:'+str(two.report_id)]=='cannot_assess'
    s=OptionsPlatformStore(DB(tmp_path/'db'));s.put_monitoring(7,MonitoringSettings(enabled=True),now=0)
    c=s.claim_monitor(7,'g',now=0);s.finish_monitor(7,c,states(first),now=1)
    c=s.claim_monitor(7,'g',now=61);s.finish_monitor(7,c,states(missing),now=62)
    assert not any(a['kind']=='recovery' for a in s.list_alerts(7))
    assert any(a['key']=='capital' and a['kind']=='data_quality' for a in s.list_alerts(7))


def test_round_trip_net_quantity_does_not_prove_remaining_selected_lot():
    from app.terminal.options_monitoring import association_pnl
    from app.terminal.portfolio_contracts import PortfolioRow
    req,ev=fixture();report=analyze_strategy(req,ev,None,NOW)
    ids=[req.stock_contract_id,req.call_contract_id]
    # The selected first stock buy was closed by a sale and replaced by a later
    # buy at120. Same net100 cannot allocate any current units to that first buy.
    rows=[PortfolioRow(row_id=str(i),exchange=id.split('|')[0] if '|' in id else 'x',token=id.split('|')[-1],quantity=100 if i==0 else -100,last_price='125' if i==0 else '3',identity_verified=True,currency='INR',inventory_coverage='disjoint',inventory_coverage_basis='fixture') for i,id in enumerate(ids)]
    req=req.model_copy(update={'stock_contract_id':'x|stock','call_contract_id':'x|call'})
    report=report.model_copy(update={'request':req})
    rows[0].exchange='x';rows[0].token='stock';rows[1].exchange='x';rows[1].token='call'
    trades=[dict(fill_id='old-buy',contract_id='x|stock',side='BUY',quantity='100',price='100'),dict(fill_id='close',contract_id='x|stock',side='SELL',quantity='100',price='110'),dict(fill_id='reopen',contract_id='x|stock',side='BUY',quantity='100',price='120'),dict(fill_id='call',contract_id='x|call',side='SELL',quantity='100',price='5')]
    result=association_pnl(report,rows,[trades[0],trades[3]],costs_inr=Decimal(10))
    assert result['status']=='cannot_assess'
    assert result['realized_inr'] is None and result['unrealized_inr'] is None and result['yield_fraction'] is None
    assert result['comparison_label']=='mark_versus_selected_fills_not_actual_pnl'


def test_acquisition_failure_transitions_deduplicate_and_cancel_has_no_publication(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from app.terminal.options_monitoring import OptionsMonitoringService
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.options_platform_risk import MonitoringSettings
    from test_options_platform_api import agent_stub
    async def run():
        a=agent_stub();s=OptionsPlatformStore(DB(tmp_path/'db'));clock=[0]
        a.market.get_session=lambda owner:SimpleNamespace(generation='g',source='kotak',broker=SimpleNamespace(is_authenticated=True))
        s.put_monitoring(7,MonitoringSettings(enabled=True),now=0)
        c=s.claim_monitor(7,'g',now=0);s.finish_monitor(7,c,{'capital':'pass'},now=1)
        p=OptionsPlatformService(a,s);m=OptionsMonitoringService(p,clock=lambda:clock[0])
        def failed(*args):raise RuntimeError('provider unavailable')
        m._fetch=failed
        for now in (61,122):
            clock[0]=now;a.refresh_last.clear();c=s.claim_monitor(7,'g',now=now)
            await m._tick(7,c)
        alerts=s.list_alerts(7)
        assert len(alerts)==1 and alerts[0]['key']=='capital' and alerts[0]['kind']=='data_quality'
        assert s.get_monitoring(7)['status']=='pending'
        reports=s.list_private_records(7,'risk')
        assert reports[0]['acquisition_status']=='unavailable' and reports[0]['checks'][0]['evidence_ids']==[]
        async def cancelled(*args,**kw):raise asyncio.CancelledError()
        p._admitted=cancelled;clock[0]=183;c=s.claim_monitor(7,'g',now=183)
        with pytest.raises(asyncio.CancelledError):await m._tick(7,c)
        assert len(s.list_private_records(7,'risk'))==2 and len(s.list_alerts(7))==1
    asyncio.run(run())


def test_complete_user_declared_lot_ledger_tracks_round_trip_and_remaining_lots():
    from app.terminal.options_lot_ledger import LotLedgerImport,assess_lot_ledger
    from app.terminal.portfolio_contracts import PortfolioRow
    from datetime import timedelta
    req,ev=fixture();report=analyze_strategy(req,ev,None,NOW)
    report=report.model_copy(update={'request':req.model_copy(update={'stock_contract_id':'x|stock','call_contract_id':'x|call'})})
    rows=[PortfolioRow(row_id='s',exchange='x',token='stock',quantity=100,last_price=125,identity_verified=True,currency='INR',inventory_coverage='disjoint',inventory_coverage_basis='fixture'),PortfolioRow(row_id='c',exchange='x',token='call',quantity=-100,last_price=3,identity_verified=True,currency='INR',inventory_coverage='disjoint',inventory_coverage_basis='fixture')]
    def trade(i,id,side,price):return dict(sequence=i,fill_id=str(i),contract_id=id,side=side,quantity=100,price=str(price),costs_inr='10',executed_at=(NOW-timedelta(minutes=10-i)).isoformat())
    ledger=LotLedgerImport(coverage_start=NOW-timedelta(hours=1),coverage_end=NOW,opening_inventory=[dict(contract_id=id,quantity=0) for id in ('x|stock','x|call')],trades=[trade(0,'x|stock','BUY',100),trade(1,'x|call','SELL',5),trade(2,'x|stock','SELL',110),trade(3,'x|stock','BUY',120)])
    result=assess_lot_ledger(report,rows,('0','1'),ledger,snapshot_observed_at=NOW)
    assert result['status']=='assessed' and result['source']=='user_declared'
    assert Decimal(result['realized_inr'])==980 and Decimal(result['unrealized_inr'])==190
    assert result['current_coverage_verified'] is False
    assert result['selected_remaining_quantity']=={'x|stock':'0','x|call':'100'}
    assert result['execution_confirmed'] is True
    assert assess_lot_ledger(report,rows,('0','1'),ledger.model_copy(update={'complete':False}),snapshot_observed_at=NOW)['status']=='cannot_assess'
    assert assess_lot_ledger(report,rows,('0','1'),ledger,snapshot_observed_at=NOW+timedelta(seconds=1))['status']=='cannot_assess'
    assert assess_lot_ledger(report,rows,('2','1'),ledger,snapshot_observed_at=NOW)['status']=='cannot_assess'


def test_lot_ledger_import_api_owner_and_provenance(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.terminal.routers.options_platform import options_platform_router
    app=FastAPI();app.include_router(options_platform_router)
    app.state.options_platform_store=OptionsPlatformStore(DB(tmp_path/'db'))
    @app.middleware('http')
    async def owner(request,call_next):
        request.state.user={'id':int(request.headers.get('Owner','7'))};return await call_next(request)
    client=TestClient(app)
    body=dict(coverage_start=NOW.isoformat(),coverage_end=NOW.isoformat(),opening_inventory=[dict(contract_id='x|stock',quantity=0)],trades=[])
    response=client.post('/api/options-platform/lot-ledger-imports',json=body)
    assert response.status_code==200 and response.json()['source']=='user_declared'
    assert len(client.get('/api/options-platform/lot-ledger-imports').json())==1
    assert client.get('/api/options-platform/lot-ledger-imports',headers={'Owner':'8'}).json()==[]
    assert client.post('/api/options-platform/lot-ledger-imports',json=dict(body,source='broker_verified')).status_code==422


def test_session_loss_before_due_transitions_once_and_reconnects_next_cycle(tmp_path):
    import asyncio
    from datetime import UTC,datetime
    from types import SimpleNamespace
    from app.terminal.options_monitoring import OptionsMonitoringService
    from app.terminal.options_platform_service import OptionsPlatformService
    from app.terminal.options_platform_risk import MonitoringSettings,PlatformRiskPolicy
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    from test_options_platform_api import agent_stub
    async def run():
        a=agent_stub();s=OptionsPlatformStore(DB(tmp_path/'db'));clock=[NOW.timestamp()]
        session=SimpleNamespace(generation='g',source='kotak',broker=SimpleNamespace(is_authenticated=True))
        a.market.get_session=lambda owner:session
        def fetch(*args,**kwargs):
            stamp=datetime.fromtimestamp(clock[0],UTC)
            return PortfolioSnapshot(retrieval_started_at=stamp,retrieval_finished_at=stamp,source_observed_at=stamp)
        a.mcp.portfolio_service=SimpleNamespace(fetch=fetch,assert_generation=lambda *a,**k:None,_acquire=lambda lock,deadline:lock.acquire())
        m=OptionsMonitoringService(OptionsPlatformService(a,s),clock=lambda:clock[0])
        s.put_risk_policy(7,PlatformRiskPolicy(observation_max_age_seconds=60))
        s.put_monitoring(7,MonitoringSettings(enabled=True),now=clock[0])
        claim=s.claim_monitor(7,'g',now=clock[0]);await m._tick(7,claim)
        assert s.list_private_records(7,'risk')[0]['checks'][0]['outcome']=='pass'
        assert s.get_monitoring(7)['next_due']==clock[0]+60
        clock[0]+=1;session.source='demo';session.broker.is_authenticated=False
        await m.run_due()
        alerts=s.list_alerts(7)
        assert s.get_monitoring(7)['status']=='suspended'
        assert len(alerts)==1 and alerts[0]['kind']=='data_quality' and alerts[0]['key']=='observation_age'
        assert s.list_private_records(7,'risk')[0]['acquisition_status']=='unavailable'
        assert s.list_private_records(8,'risk')==[] and s.list_alerts(8)==[]
        for advance in (1,59,1000):
            clock[0]+=advance;await m.run_due()
        assert len(s.list_alerts(7))==1 and len(s.list_private_records(7,'risk'))==2
        session.source='kotak';session.broker.is_authenticated=True;session.generation='new'
        await m.run_due()
        assert s.get_monitoring(7)['status']=='pending' and s.get_monitoring(7)['next_due']==clock[0]+60
        clock[0]+=59;await m.run_due();assert not m.ticks
        clock[0]+=1;a.refresh_last.clear();await m.run_due()
        await asyncio.gather(*tuple(m.ticks.values()));await asyncio.sleep(0)
        assert s.get_monitoring(7)['generation']=='new' and s.get_monitoring(7)['status']=='pending'
        assert s.list_private_records(7,'risk')[0]['checks'][0]['outcome']=='pass'
        assert len(s.list_alerts(7))==1 and not any(a['kind']=='recovery' for a in s.list_alerts(7))
    asyncio.run(run())


def test_unavailable_claim_generation_lease_cancel_rollback_and_suspended_retry(tmp_path):
    from app.terminal.options_platform_risk import MonitoringSettings
    s=OptionsPlatformStore(DB(tmp_path/'db'));s.put_monitoring(7,MonitoringSettings(enabled=True),now=0)
    claim=s.claim_monitor(7,'g',now=0);s.finish_monitor(7,claim,{'capital':'pass'},now=1)
    assert s.claim_monitor_unavailable(8,'g',now=2) is None
    assert s.claim_monitor_unavailable(7,'other-generation',now=2) is None
    claim=s.claim_monitor_unavailable(7,'g',now=2)
    assert claim and s.claim_monitor_unavailable(7,'g',now=3) is None
    def cancelled():raise TimeoutError()
    with pytest.raises(TimeoutError):s.finish_monitor_unavailable(7,claim,now=3,_check=cancelled)
    assert s.list_alerts(7)==[] and s.list_private_records(7,'risk')==[]
    s.suspend_monitor(7,now=3)
    retry=s.claim_monitor_unavailable(7,'g',now=3)
    assert retry and not s.finish_monitor_unavailable(7,claim,now=3)
    assert s.finish_monitor_unavailable(7,retry,now=3)
    assert len(s.list_alerts(7))==1 and s.claim_monitor_unavailable(7,'g',now=4) is None
