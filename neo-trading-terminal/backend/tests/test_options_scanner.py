from decimal import Decimal
import pytest
from pydantic import ValidationError
from test_options_strategies import fixture, NOW
from app.terminal.options_scanner import ScanCriteria, scan_evidence, rank_candidates
import asyncio
import functools
def async_test(fn):
    @functools.wraps(fn)
    def run(*args,**kwargs):return asyncio.run(fn(*args,**kwargs))
    return run

def criteria(**kw):
    value=dict(capital_inr='20000',strategy='covered_call',scope='hypothetical',min_expiry_days=1,max_expiry_days=60,
        minimum_volume='0',minimum_open_interest='0',minimum_depth='100',maximum_relative_spread='0.1',maximum_loss_inr='20000',quote_max_age_seconds=60,
        costs=dict(opening_fees_inr='10',expiry_fees_inr='0',stock_slippage_per_unit='0',call_slippage_per_unit='0',put_slippage_per_unit='0'))
    value.update(kw);return ScanCriteria(**value)

def evidence():
    _,ev=fixture()
    return ev.model_copy(update={'quotes':tuple(q.model_copy(update={'volume':Decimal(100),'open_interest':Decimal(200)}) for q in ev.quotes)})

def test_positive_engine_path_and_boundary():
    result=scan_evidence(criteria(),evidence(),(),NOW)
    assert len(result['candidates'])==1
    assert result['candidates'][0]['report']['status']=='eligible'
    assert scan_evidence(criteria(minimum_depth='101'),evidence(),(),NOW)['candidates']==[]

@pytest.mark.parametrize('kw',[{'capital_inr':True},{'minimum_volume':'NaN'},{'min_expiry_days':False},{'maximum_relative_spread':'-1'},{'max_expiry_days':0}])
def test_invalid(kw):
    with pytest.raises(ValidationError): criteria(**kw)

def test_missing_liquidity_fails_closed():
    _,ev=fixture()
    assert scan_evidence(criteria(),ev,(),NOW)['exclusions'][0]['reason']=='liquidity_missing'

def test_rank_stability():
    rows=[dict(group=['covered_call',30,'current'],net_horizon_yield='0.1',relative_spread='0',minimum_volume='100',minimum_open_interest='200',contracts=[x]) for x in ['b','a']]
    assert rank_candidates(rows)==rank_candidates(list(reversed(rows)))
    assert rank_candidates(rows)[0]['contracts']==['a']

def service(tmp_path,*,acquire=None,clock=None):
    from app.terminal.options_scan_jobs import OptionsScannerService
    from app.terminal.options_platform_store import OptionsPlatformStore
    from app.terminal.options_platform_service import OptionsPlatformService
    from test_options_platform_api import DB,agent_stub
    a=agent_stub();a.deadline_seconds=10
    platform=OptionsPlatformService(a,OptionsPlatformStore(DB(tmp_path/'scan.db')))
    universe=lambda:dict(version='fixture',status='complete',as_of=NOW.isoformat(),instrument_ids=['call'],hash='fixture',total_contracts=3,underlyings=[dict(underlying='stock',expiries=['2026-12-01'])])
    return OptionsScannerService(platform,acquire=acquire or (lambda *args:(evidence(),())),universe=universe,clock=clock or (lambda:NOW.timestamp()))

@async_test
async def test_real_job_positive_owner_and_immutable_report(tmp_path):
    s=service(tmp_path);job=s.create(7,criteria())
    assert s.jobs.get(8,job['id']) is None
    assert await s.tick()
    saved=s.jobs.get(7,job['id'])
    assert saved['status']=='completed'
    assert len(saved['report']['candidates'])==1
    assert saved['report']['evidence_ids']
    assert s.jobs.cancel(8,job['id']) is None
    assert s.jobs.cancel(7,job['id'])['status']=='completed'
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        with s.platform.store._db() as db:db.execute('DELETE FROM platform_scan_reports')

@async_test
async def test_quota_wait_restart_cursor_and_global_heavy(tmp_path):
    from fastapi import HTTPException
    now=[NOW.timestamp()]
    def quota(*args): raise HTTPException(429,'quota',headers={'Retry-After':'120'})
    s=service(tmp_path,acquire=quota,clock=lambda:now[0]);job=s.create(7,criteria())
    assert await s.tick()
    saved=s.jobs.get(7,job['id']);assert saved['status']=='paused_quota' and saved['next_due']==now[0]+120 and saved['cursor']==0
    assert not await s.tick()
    backtest=s.platform.store.enqueue_heavy(8,'backtest',now=now[0]);claim=s.platform.store.claim_heavy(now=now[0],kind='backtest')
    assert claim['id']==backtest
    now[0]+=120;assert not await s.tick() # ANY running kind blocks a scan
    s.platform.store.finish_heavy(8,backtest,claim['token'])
    # Reconstruct a durable interrupted scan and verify startup resumes cursor.
    with s.platform.store._db() as db:db.execute("UPDATE platform_heavy SET status='running' WHERE id=?",(job['id'],))
    s.jobs.recover();s.acquire=lambda *args:(evidence(),());s.platform.agent.refresh_last.clear()
    assert await s.tick();assert s.jobs.get(7,job['id'])['status']=='completed'
    backtest=s.platform.store.enqueue_heavy(8,'backtest',now=now[0])
    claim=s.platform.store.claim_heavy(now=now[0],kind='backtest');assert claim['id']==backtest
    assert not await s.tick()

@async_test
async def test_cancel_blocked_retains_heavy_and_no_late_publish(tmp_path):
    import asyncio
    from threading import Event
    entered=Event();release=Event()
    def acquire(*args):entered.set();release.wait(5);return evidence(),()
    s=service(tmp_path,acquire=acquire);job=s.create(7,criteria())
    task=asyncio.create_task(s.tick())
    assert await asyncio.to_thread(entered.wait,2)
    s.jobs.cancel(7,job['id'])
    s.platform.store.enqueue_heavy(8,'backtest',now=NOW.timestamp())
    assert s.platform.store.claim_heavy(now=NOW.timestamp()) is None
    assert 7 in s.platform.agent.refresh_active
    release.set();await task
    saved=s.jobs.get(7,job['id']);assert saved['status']=='cancelled' and saved['report'] is None and not saved['evidence_ids']
    assert s.platform.store.claim_heavy(now=NOW.timestamp())['kind']=='backtest'

@async_test
async def test_start_stop_executes_without_manual_tick(tmp_path):
    import asyncio
    s=service(tmp_path);job=s.create(7,criteria());await s.start()
    for _ in range(50):
        if s.jobs.get(7,job['id'])['status']=='completed':break
        await asyncio.sleep(.02)
    await s.stop()
    assert s.jobs.get(7,job['id'])['status']=='completed'

def test_universe_exact_stock_scope_unknown_and_expiry():
    from app.terminal.options_scan_jobs import catalogue_universe
    from types import SimpleNamespace
    rows=[dict(id=id,underlying='NIFTY-looking-stock',expiry=expiry,source_metadata=dict(source='kotak-scrip-master',pInstType=kind)) for id,kind,expiry in [('stock','OPTSTK','2026-12-01'),('index','OPTIDX','2026-12-01'),('expired','OPTSTK','2026-11-01')]]
    store=SimpleNamespace(search=lambda **kw:dict(items=rows,total=len(rows)))
    result=catalogue_universe(store,NOW)
    assert result['instrument_ids']==['stock'] and result['status']=='complete'
    rows.append(dict(id='unknown',underlying='STOCK',expiry='2026-12-01'))
    assert catalogue_universe(store,NOW)['status']=='unavailable'

@async_test
async def test_resume_actual_nonzero_cursor_and_network_partial(tmp_path):
    now=[NOW.timestamp()];s=service(tmp_path,clock=lambda:now[0])
    u=s.universe();u['underlyings']*=2;s.universe=lambda:u
    job=s.create(7,criteria());await s.tick()
    assert s.jobs.get(7,job['id'])['cursor']==1
    resumed=service(tmp_path,clock=lambda:now[0]);resumed.jobs.recover();now[0]+=5
    def fail(*args):raise ConnectionError('private provider detail')
    resumed.acquire=fail;await resumed.tick()
    now[0]+=5;await resumed.tick()
    saved=resumed.jobs.get(7,job['id'])
    assert saved['status']=='partial' and saved['cursor']==2
    assert saved['report']['missing_underlyings']==1
    assert 'private provider' not in str(saved)

@async_test
async def test_three_quota_retries_finish_partial(tmp_path):
    from app.terminal.market import MarketQuotaError
    now=[NOW.timestamp()]
    def quota(*args):raise MarketQuotaError(999)
    s=service(tmp_path,acquire=quota,clock=lambda:now[0]);job=s.create(7,criteria())
    for i in range(3):
        s.platform.agent.refresh_last.clear();await s.tick()
        saved=s.jobs.get(7,job['id'])
        if i<2:assert saved['next_due']==now[0]+300
        now[0]+=300
    assert saved['status']=='partial' and saved['cursor']==0

def test_api_owner_scope_and_reject_public_metadata(tmp_path):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from app.terminal.routers.options_platform import options_platform_router
    s=service(tmp_path);app=FastAPI();app.include_router(options_platform_router);app.state.options_scanner_service=s
    @app.middleware('http')
    async def owner(request:Request,call_next):
        if request.headers.get('owner'):request.state.user={'id':int(request.headers['owner'])}
        return await call_next(request)
    client=TestClient(app)
    assert client.post('/api/options-platform/scans',json=criteria().model_dump(mode='json')).status_code==401
    r=client.post('/api/options-platform/scans',headers={'owner':'7'},json=criteria().model_dump(mode='json'))
    assert r.status_code==200
    id=r.json()['id']
    assert client.get('/api/options-platform/scans/'+id,headers={'owner':'8'}).status_code==404
    assert client.post('/api/options-platform/scans/'+id+'/cancel',headers={'owner':'8'}).status_code==404
    payload=criteria().model_dump(mode='json');payload['settlement_verified']=True
    assert client.post('/api/options-platform/scans',headers={'owner':'7'},json=payload).status_code==422

def test_exact_official_rule_requires_current_individual_contract_proof():
    from app.terminal.options_strategies import _settlement_rule
    _,ev=fixture();call=ev.contracts[1]
    official=call.model_copy(update={'settlement_rule_version':'nse-optstk-physical-2019.v1','provenance':('kotak-scrip-master:pInstType=OPTSTK',)})
    live=ev.model_copy(update={'source':'kotak-scanner'})
    assert _settlement_rule(official,live) is None
    official=official.model_copy(update={'provenance':official.provenance+('verified current NSE OPTSTK identity, lot and corporate-action deliverable',)})
    assert _settlement_rule(official,live).applicability=='verified_nse_optstk'
    assert _settlement_rule(official,ev) is None

@async_test
async def test_real_acquisition_helper_uses_owner_and_no_hypothetical_portfolio(tmp_path,monkeypatch):
    import app.terminal.options_scan_jobs as module
    calls=[]
    def fetch(market,store,owner,context,deadline=None):calls.append((owner,context.underlying,deadline));return evidence()
    monkeypatch.setattr(module,'fetch_strategy_market_evidence',fetch)
    s=service(tmp_path);s.acquire=s._acquire
    job=s.create(7,criteria());await s.tick()
    assert calls and calls[0][0:2]==(7,'STOCK') and calls[0][2] is not None
    saved=s.jobs.get(7,job['id'])
    assert saved['evidence_ids'] and saved['status']=='partial'
    # Synthetic semantics must not leak into live-adapter evidence.
    assert not saved['report']['candidates']

def test_collar_and_distinct_horizon_groups():
    result=scan_evidence(criteria(strategy='collar'),evidence(),(),NOW)
    assert result['candidates'][0]['contracts']==['stock','call','put']
    assert result['candidates'][0]['report']['current_basis']['maximum_loss']=='710'
    row=result['candidates'][0];other=dict(row,group=['covered_call',30,'current'],net_horizon_yield='999')
    assert rank_candidates([row,other])[0]['group'][0]=='collar' # separate groups, no universal ranking

def test_queue_bound_and_page_validation(tmp_path):
    from app.terminal.options_platform_store import PlatformConflictError
    s=service(tmp_path)
    for i in range(20):s.create(7,criteria())
    with pytest.raises(PlatformConflictError):s.create(8,criteria())
    assert len(s.jobs.list(7))==20 and not s.jobs.list(8)
    with pytest.raises(ValueError):s.jobs.list(7,limit=101)

@async_test
async def test_unavailable_universe_report(tmp_path):
    s=service(tmp_path);u=s.universe();u['status']='unavailable';s.universe=lambda:u
    job=s.create(7,criteria());await s.tick();saved=s.jobs.get(7,job['id'])
    assert saved['status']=='partial' and saved['report']['exclusions'][0]['reason']=='universe_unavailable'

@async_test
async def test_missing_leg_continues_and_counts_combinations(tmp_path):
    now=[NOW.timestamp()];calls=[]
    def acquire(*args):
        calls.append(1);ev=evidence()
        if len(calls)==1:ev=ev.model_copy(update={'contracts':tuple(c for c in ev.contracts if c.kind!='equity'),'quotes':tuple(q for q in ev.quotes if q.contract_id!='stock')})
        return ev,()
    s=service(tmp_path,acquire=acquire,clock=lambda:now[0]);u=s.universe();u['underlyings']*=2;s.universe=lambda:u
    job=s.create(7,criteria());await s.tick()
    assert s.jobs.get(7,job['id'])['status']=='queued'
    now[0]+=5;s.platform.agent.refresh_last.clear();await s.tick()
    report=s.jobs.get(7,job['id'])['report']
    assert len(report['candidates'])==1
    assert (report['visited_combinations'],report['total_combinations'],report['missing_combinations'])==(1,2,1)

@async_test
async def test_generation_change_after_calculation_blocks_publication(tmp_path,monkeypatch):
    import app.terminal.options_scan_jobs as module
    generation=['g'];original=module.scan_evidence
    def calculate(*args,**kwargs):
        result=original(*args,**kwargs);generation[0]='new';return result
    monkeypatch.setattr(module,'scan_evidence',calculate)
    s=service(tmp_path);s.platform.agent.market.session_generation=lambda owner:generation[0]
    job=s.create(7,criteria(scope='owned'));await s.tick()
    saved=s.jobs.get(7,job['id']);assert saved['report'] is None and not saved['candidates']

@async_test
async def test_terminal_storage_busy_retries_and_next_job_runs(tmp_path,monkeypatch):
    from app.terminal.options_platform_store import PlatformStoreBusyError
    now=[NOW.timestamp()];s=service(tmp_path,clock=lambda:now[0]);job=s.create(7,criteria())
    original=s.jobs.publish;attempts=[]
    def publish(*args,**kwargs):
        attempts.append(1)
        if len(attempts)==1:raise PlatformStoreBusyError('busy')
        return original(*args,**kwargs)
    monkeypatch.setattr(s.jobs,'publish',publish)
    await s.tick()
    assert s.jobs.get(7,job['id'])['status']=='running'
    now[0]+=5;await s.tick()
    assert s.jobs.get(7,job['id'])['report']['candidates']
    next_job=s.create(8,criteria());await s.tick()
    assert s.jobs.get(8,next_job['id'])['status']=='completed'

@async_test
async def test_generation_change_between_worker_and_commit(tmp_path,monkeypatch):
    s=service(tmp_path);generation=['g'];s.platform.agent.market.session_generation=lambda owner:generation[0]
    admitted=s.platform._admitted
    async def finish(*args,**kwargs):
        result=await admitted(*args,**kwargs);generation[0]='new';return result
    monkeypatch.setattr(s.platform,'_admitted',finish)
    job=s.create(7,criteria());await s.tick()
    saved=s.jobs.get(7,job['id'])
    assert saved['status']=='cancelled' and saved['report'] is None and saved['candidates']==[]

def test_budget_exhaustion_distinct_from_missing_legs():
    result=scan_evidence(criteria(),evidence(),(),NOW,combination_limit=0)
    assert result['partial'] and result['budget_exhausted']
    assert (result['visited_combinations'],result['total_combinations'],result['missing_combinations'])==(0,1,1)
