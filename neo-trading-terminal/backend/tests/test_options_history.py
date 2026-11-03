"""Independent cash/inventory goldens; no broker or market calls."""
import csv
import io
from decimal import Decimal
import pytest
from app.terminal.options_history import parse_history, HistoryStore, HistoryValidationError
from app.terminal.options_history_contracts import ImportDeclaration, BacktestRequest
from app.terminal.options_backtest import run_backtest
from test_options_platform_api import DB
from app.terminal.options_platform_store import OptionsPlatformStore

D='2026-01-01T09:00:00+05:30'
F='2026-01-01T09:01:00+05:30'
X='2026-01-29T15:30:00+05:30'

def rows(collar=False,price='120',depth='10'):
    base=dict(timestamp=D,effective_at=D,known_at=D,source='synthetic-test')
    result=[]
    for id,kind,strike in [('S','equity',None),('C','call','110')]+([('P','put','90')] if collar else []):
        result.append(dict(base,row_type='contract',record_id='contract-'+id,contract_id=id,kind=kind,underlying_id='S',exchange='NSE',currency='INR',lot_size='10',expiry='' if kind=='equity' else '2026-01-29',strike=strike or '',deliverable_quantity='1',adjustment_id='original',settlement_rule='physical-european.1'))
        for i,t in enumerate([D,F]):
            bid,ask=('99','100') if id=='S' else ('5','6') if id=='C' else ('2','3')
            result.append(dict(base,row_type='quote',record_id=f'q-{id}-{i}',contract_id=id,timestamp=t,effective_at=t,known_at=t,bid=bid,ask=ask,bid_quantity=depth,ask_quantity=depth))
        if id!='S':
            result.append(dict(base,row_type='settlement',record_id='expiry-'+id,contract_id=id,timestamp=X,effective_at=X,known_at=X,price=price,settlement_rule='physical-european.1',verified='true'))
    result.append(dict(base,row_type='quote',record_id='end-S',contract_id='S',timestamp=X,effective_at=X,known_at=X,bid=price,ask=price,bid_quantity=depth,ask_quantity=depth))
    return result

def csv_bytes(data):
    stream=io.StringIO();fields=sorted({k for r in data for k in r});writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(data);return stream.getvalue().encode()

def declaration(collar=False):
    return ImportDeclaration(provenance='Synthetic fixture, invented values',licence='Own synthetic data',dataset_status='synthetic',expected_intervals=[dict(contract_id=id,start=D,end=F,interval_seconds=60) for id in (['S','C','P'] if collar else ['S','C'])])

def dataset(collar=False,**kw):return parse_history(csv_bytes(rows(collar,**kw)),'csv',declaration(collar))

def request(collar=False,**kw):
    data=dict(dataset_id='00000000-0000-0000-0000-000000000001',kind='collar' if collar else 'covered_call',mode='hypothetical',entries=[dict(decision_at=D,stock_contract_id='S',call_contract_id='C',quantity=10,**({'put_contract_id':'P'} if collar else {}))],start=D,end=X,initial_capital='2000',costs=dict(source='user-test',opening_fee_inr='1',expiry_fee_inr='1',slippage_per_unit='0.1'),quote_max_age_seconds=120,valuation_times=[D,F,X])
    data.update(kw);return BacktestRequest(**data)

def test_import_exact_and_immutable_owner(tmp_path):
    parsed=dataset();assert parsed['rows'][0]
    store=HistoryStore(OptionsPlatformStore(DB(tmp_path/'history.db')))
    manifest=store.save(7,parsed);assert manifest['status']=='validated'
    assert store.get(8,manifest['id']) is None
    assert store.load(8,manifest['id']) is None
    assert 'rows' not in store.get(7,manifest['id'])
    assert store.load(7,manifest['id'])['content_hash']==parsed['content_hash']
    with store.platform._db() as db:
        with pytest.raises(Exception):db.execute('UPDATE options_history SET manifest=?',('{}',))

def test_csv_parquet_equivalence():
    pa = pytest.importorskip('pyarrow')
    import pyarrow.parquet as pq
    data=rows();fields=sorted({k for r in data for k in r})
    table=pa.Table.from_pylist([{k:r.get(k) or None for k in fields} for r in data]);out=io.BytesIO();pq.write_table(table,out)
    assert parse_history(out.getvalue(),'parquet',declaration())==dataset()

@pytest.mark.parametrize('field,value',[('bid','NaN'),('bid','Infinity'),('bid','true'),('known_at','2026-01-01T09:00:00'),('exchange','BSE'),('row_type','pickle')])
def test_invalid_sanitized(field,value):
    data=rows();index=0 if field in ('exchange','row_type') else 1;data[index][field]=value
    with pytest.raises(HistoryValidationError) as error:parse_history(csv_bytes(data),'csv',declaration())
    assert error.value.row==index+2;assert value not in error.value.message

def test_conflicts_references_gaps_and_size():
    data=rows();data.append(dict(data[1],bid='1'))
    with pytest.raises(HistoryValidationError):parse_history(csv_bytes(data),'csv',declaration())
    data=rows();data[1]['contract_id']='unknown'
    with pytest.raises(HistoryValidationError):parse_history(csv_bytes(data),'csv',declaration())
    with pytest.raises(HistoryValidationError):parse_history(b'x'*(10*1024*1024+1),'csv',declaration())
    data=rows();data=[r for r in data if r['record_id']!='q-C-1']
    parsed=parse_history(csv_bytes(data),'csv',declaration());assert parsed['coverage']['gaps']
    with pytest.raises(ValueError,match='unsupported_period'):run_backtest(parsed,request())

def test_covered_call_golden_physical_delivery():
    report=run_backtest(dataset(),request())
    # Buy 10 at 100.1, sell 10 calls at 4.9, opening fees 2.
    # Physical assignment receives strike proceeds 1100, expiry fee 1.
    assert report['cash']=='2145';assert report['inventory']=={'S':'0','C':'0'}
    assert report['net_profit']=='145';assert report['total_fees']=='3'
    from app.terminal.options_history import stamp
    assert report['trades'][0]['filled_at']==stamp(F)
    assert report['attribution'][0]['expiry_expected_profit']=='145'
    assert report['attribution'][0]['realised_profit']=='145'
    assert report['attribution'][0]['expiry_difference']=='0'
    assert report['performance_status']=='complete'

def test_collar_put_golden():
    report=run_backtest(dataset(True,price='80'),request(True))
    # Initial 2000 -1001+49-31-3; put delivers stock for 900; fees 2.
    assert report['cash']=='1912';assert report['net_profit']=='-88'
    assert report['inventory']=={'S':'0','C':'0','P':'0'}
    assert report['attribution'][0]['expiry_expected_profit']=='-88'

def test_depth_lot_caps_and_no_depth():
    report=run_backtest(dataset(depth='5'),request());assert report['trades'][0]['quantity']==0
    data=rows();[r.pop(k,None) for r in data for k in ('bid_quantity','ask_quantity')]
    parsed=parse_history(csv_bytes(data),'csv',declaration())
    assert run_backtest(parsed,request())['trades'][0]['unfilled_quantity']==10
    result=run_backtest(parsed,request(fill_policy='assume_unlimited_depth'))
    assert result['confidence']=='low';assert result['net_profit']=='145'

def test_lookahead_and_expiry_missing():
    data=rows();data[1]['known_at']=X
    with pytest.raises(ValueError,match='decision_evidence'):run_backtest(parse_history(csv_bytes(data),'csv',declaration()),request())
    data=[r for r in rows() if r['row_type']!='settlement']
    with pytest.raises(ValueError,match='settlement_missing'):run_backtest(parse_history(csv_bytes(data),'csv',declaration()),request())

def test_stale_marks_no_performance_claim():
    r=request(valuation_times=['2026-01-02T09:00:00+05:30'])
    report=run_backtest(dataset(),r);assert report['performance_status']=='unavailable_segments'
    assert report['max_drawdown'] is None

def test_unsupported_action_and_missing_adjustment():
    data=rows();base=dict(data[0],row_type='corporate_action',record_id='action',action='merger',amount='1')
    with pytest.raises(HistoryValidationError):parse_history(csv_bytes(data+[base]),'csv',declaration())
    base['action']='split';base['ratio']='2'
    with pytest.raises(HistoryValidationError):parse_history(csv_bytes(data+[base]),'csv',declaration())

def test_parquet_floats_row_count_and_decimal():
    pa = pytest.importorskip('pyarrow')
    import pyarrow.parquet as pq
    table=pa.table({'row_type':['quote'],'bid':[1.0]});out=io.BytesIO();pq.write_table(table,out)
    with pytest.raises(HistoryValidationError):parse_history(out.getvalue(),'parquet',declaration())
    data=rows();data[1]['bid']='99.123456789012'
    parsed=parse_history(csv_bytes(data),'csv',declaration())
    assert next(r for r in parsed['rows'] if r['record_id']=='q-S-0')['bid']=='99.123456789012'
    # Decimal scale must not change the immutable semantic manifest hash.
    data=rows();data[1]['bid']='99.0000'
    assert parse_history(csv_bytes(data),'csv',declaration())['content_hash']==dataset()['content_hash']

def test_restart_cancel_lease_owner_and_due(tmp_path):
    from app.terminal.options_backtest_jobs import BacktestService
    platform=OptionsPlatformStore(DB(tmp_path/'jobs.db'));service=BacktestService(platform,clock=lambda:100.)
    manifest=service.history.save(7,dataset());r=request(dataset_id=manifest['id'])
    job=service.create(7,r)
    assert service.get(8,job['id']) is None
    assert service.tick_sync()
    cursor=service.get(7,job['id'])['cursor'];assert cursor==1
    restarted=BacktestService(platform,clock=lambda:101.)
    while restarted.get(7,job['id'])['status'] not in ('completed','failed'):assert restarted.tick_sync()
    report=restarted.get(7,job['id'])['report'];assert report['net_profit']=='145'
    job=service.create(7,r);assert service.cancel(8,job['id']) is None
    assert service.cancel(7,job['id'])['status']=='cancelled';assert not service.tick_sync()
    scan=platform.enqueue_heavy(7,'scan',now=0);job=service.create(7,r)
    assert service.tick_sync() # Only claims backtest, never a scan.
    with platform._db() as db:assert db.execute('SELECT status FROM platform_heavy WHERE id=?',(scan,)).fetchone()[0]=='pending'
    active=platform.claim_heavy(now=100,kind='scan');assert active
    assert not service.tick_sync() # Any running kind blocks.
    platform.finish_heavy(7,scan,active['token'])
    service.defer(7,job['id'],next_due=200)
    assert not service.tick_sync();assert service.get(7,job['id'])['cursor']==1

def test_history_api_authenticated_owner_validation_and_backtest(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.terminal.routers.options_platform import options_platform_router
    from app.terminal.options_backtest_jobs import BacktestService
    app=FastAPI();app.include_router(options_platform_router)
    platform=OptionsPlatformStore(DB(tmp_path/'api.db'));service=BacktestService(platform)
    app.state.options_backtest_service=service
    @app.middleware('http')
    async def owner(req,call_next):
        if req.headers.get('Owner'):req.state.user={'id':int(req.headers['Owner'])}
        return await call_next(req)
    client=TestClient(app);body=dict(declaration().model_dump(mode='json'),format='csv',csv_text=csv_bytes(rows()).decode())
    assert client.post('/api/options-platform/historical-imports',json=body).status_code==401
    imported=client.post('/api/options-platform/historical-imports',json=body,headers={'Owner':'7'})
    assert imported.status_code==200;id=imported.json()['id']
    assert client.get('/api/options-platform/historical-imports/'+id,headers={'Owner':'8'}).status_code==404
    response=client.post('/api/options-platform/backtests',json=request(dataset_id=id).model_dump(mode='json'),headers={'Owner':'7'})
    assert response.status_code==200;job=response.json()
    while service.get(7,job['id'])['status'] not in ('completed','failed'):service.tick_sync()
    assert client.get('/api/options-platform/backtests/'+job['id'],headers={'Owner':'7'}).json()['report']['cash']=='2145'
    body['csv_text']=body['csv_text'].replace('synthetic-test','SECRET-MARKER');body['provenance']=True
    response=client.post('/api/options-platform/historical-imports',json=body,headers={'Owner':'7'})
    assert response.status_code==422;assert 'SECRET-MARKER' not in response.text

def action_dataset(action):
    from copy import deepcopy
    data=rows();at='2026-01-02T09:00:00+05:30';ratio=Decimal(2) if action=='split' else Decimal(1)
    adjusted=[]
    for row in data:
        if row['row_type']=='contract':
            r=deepcopy(row);r.update(record_id='adjusted-'+r['contract_id'],effective_at=at,timestamp=at,known_at=at,adjustment_id='action-1',lot_size=str(int(10*ratio)))
            if r.get('strike'):r['strike']=str(Decimal(r['strike'])/ratio)
            adjusted.append(r)
        if row['row_type']=='settlement':row['price']=str(Decimal(120)/ratio)
        if row['record_id']=='end-S':row['bid']=row['ask']=str(Decimal(120)/ratio)
    data+=adjusted
    data.append(dict(row_type='corporate_action',record_id='action',contract_id='S',timestamp=at,effective_at=at,known_at=at,source='synthetic-test',action=action,adjustment_id='action-1',adjusted_contract_ids='S|C',**({'ratio':'2'} if action=='split' else {'amount':'2'})))
    return parse_history(csv_bytes(data),'csv',declaration())

def test_cash_dividend_and_adjusted_split_cash_inventory():
    dividend=run_backtest(action_dataset('cash_dividend'),request())
    assert dividend['cash']=='2165';assert dividend['net_profit']=='165'
    assert any(e['kind']=='cash_dividend' and e['amount']=='20' for e in dividend['cash_ledger'])
    split=run_backtest(action_dataset('split'),request())
    assert split['cash']=='2145';assert split['net_profit']=='145'
    assert split['inventory']=={'S':'0','C':'0'}
    assert split['attribution'][0]['expiry_expected_profit'] is None

def test_lot_partial_owned_sequential_and_no_overlapping_positions():
    partial=run_backtest(dataset(depth='10'),request(entries=[dict(decision_at=D,stock_contract_id='S',call_contract_id='C',quantity=20)]))
    assert partial['trades'][0]['quantity']==10;assert partial['trades'][0]['unfilled_quantity']==10
    owned=run_backtest(dataset(),request(mode='owned',initial_inventory=[dict(contract_id='S',quantity=10,acquisition_cost_per_unit='95')]))
    # Initial equity 2990 (conservative bid), final cash 3147. Owned buys no stock.
    assert owned['cash']=='3147';assert owned['net_profit']=='157'
    with pytest.raises(ValueError,match='overlapping_positions'):
        run_backtest(dataset(),request(entries=[dict(decision_at=D,stock_contract_id='S',call_contract_id='C',quantity=10),dict(decision_at=F,stock_contract_id='S',call_contract_id='C',quantity=10)]))

def test_no_same_bar_and_later_known_fill_not_used():
    data=rows()
    for row in data:
        if row['record_id']=='q-C-1':row['known_at']=X
    report=run_backtest(parse_history(csv_bytes(data),'csv',declaration()),request())
    assert report['trades'][0]['quantity']==0;assert report['cash']=='2000'

def test_numeric_bool_strict_and_row_bound(monkeypatch):
    from app.terminal import options_history as module
    with pytest.raises(ValueError):request(initial_capital=True)
    with pytest.raises(ValueError):request(entries=[dict(decision_at=D,stock_contract_id='S',call_contract_id='C',quantity=True)])
    monkeypatch.setattr(module,'MAX_ROWS',3)
    with pytest.raises(HistoryValidationError) as error:dataset()
    assert error.value.code=='row_limit'

def test_actual_lifecycle_cancel_generation_queue_capacity(tmp_path):
    import asyncio
    asyncio.run(_actual_lifecycle(tmp_path))

async def _actual_lifecycle(tmp_path):
    import asyncio
    from app.terminal.options_backtest_jobs import BacktestService
    platform=OptionsPlatformStore(DB(tmp_path/'life.db'));service=BacktestService(platform)
    manifest=service.history.save(7,dataset());r=request(dataset_id=manifest['id'])
    job=service.create(7,r)
    await service.start()
    try:
        for i in range(100):
            if service.get(7,job['id'])['status']=='completed':break
            await asyncio.sleep(.02)
        assert service.get(7,job['id'])['report']['cash']=='2145'
    finally:await service.stop()
    # Old generation cannot publish over a recovered/reclaimed event.
    job=service.create(7,r);old=platform.claim_heavy(now=1e12,kind='backtest')
    service.recover();new=platform.claim_heavy(now=1e12,kind='backtest')
    with platform._db() as db:
        import json
        state=json.loads(db.execute('SELECT payload FROM options_backtest_jobs WHERE id=?',(job['id'],)).fetchone()[0])
    assert not service._publish(old,state,None)
    service.cancel(7,job['id']);state['cursor']=99
    assert service._publish(new,state,None)
    cancelled=service.get(7,job['id']);assert cancelled['status']=='cancelled';assert cancelled['cursor']==0
    for i in range(20):service.create(7,r)
    from app.terminal.options_platform_store import PlatformConflictError
    with pytest.raises(PlatformConflictError):service.create(7,r)

def test_otm_residual_inventory_valuation_realised_and_expectation():
    report=run_backtest(dataset(price='105'),request())
    # Calls expire OTM. Cash is 1045; retained stock worth 1050.
    assert report['cash']=='1045';assert report['inventory']=={'S':'10','C':'0'}
    assert report['net_profit']=='95'
    assert report['attribution'][0]['realised_profit']=='46'
    assert report['attribution'][0]['expiry_total_profit']=='95'
    assert report['attribution'][0]['expiry_difference']=='0'

def test_negative_depth_unknown_action_adjustments_and_coverage_fill_gap():
    data=rows();data[1]['bid_quantity']='-1'
    with pytest.raises(HistoryValidationError):parse_history(csv_bytes(data),'csv',declaration())
    # A row after a declared interval is not an execution source interval.
    decl=declaration().model_copy(update={'expected_intervals':tuple(w.model_copy(update={'end':w.start}) for w in declaration().expected_intervals)})
    with pytest.raises(ValueError,match='unsupported_period'):
        run_backtest(parse_history(csv_bytes(rows()),'csv',decl),request())

def test_storage_contention_keeps_claim_and_cursor(tmp_path,monkeypatch):
    from app.terminal.options_backtest_jobs import BacktestService
    from app.terminal.options_platform_store import PlatformStoreBusyError
    platform=OptionsPlatformStore(DB(tmp_path/'contention.db'));service=BacktestService(platform)
    manifest=service.history.save(7,dataset());job=service.create(7,request(dataset_id=manifest['id']))
    original=service.history.load
    monkeypatch.setattr(service.history,'load',lambda *args: (_ for _ in ()).throw(PlatformStoreBusyError()))
    with pytest.raises(PlatformStoreBusyError):service.tick_sync()
    assert service.get(7,job['id'])['cursor']==0
    monkeypatch.setattr(service.history,'load',original)
    assert service.tick_sync();assert service.get(7,job['id'])['cursor']==1

def test_shipped_csv_and_request_are_usable():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'examples'/'options-history'
    parsed=parse_history((root/'synthetic-collar.csv').read_bytes(),'csv',declaration(True))
    body=BacktestRequest.model_validate(json.loads((root/'backtest-request.json').read_text()))
    result=run_backtest(parsed,body)
    assert result['cash']=='2112';assert result['net_profit']=='112'

@pytest.mark.parametrize('contract_id',['S','C'])
def test_adjusted_versions_must_be_known_at_action(contract_id):
    from copy import deepcopy
    parsed=deepcopy(action_dataset('split'))
    for row in parsed['rows']:
        if row['row_type']=='contract' and row['adjustment_id']=='action-1' and row['contract_id']==contract_id:
            row['known_at']='2026-02-01T00:00:00+00:00'
    with pytest.raises(HistoryValidationError,match='adjustment_metadata'):
        parse_history(csv_bytes(parsed['rows']),'csv',declaration())
    # Defensive engine validation also protects a pre-existing stored dataset.
    with pytest.raises(ValueError,match='corporate_action_late_metadata'):
        run_backtest(parsed,request())

def unselected_owned_dataset(action,missing_quote=False):
    from copy import deepcopy
    data=rows();at='2026-01-02T09:00:00+05:30'
    extra=[]
    for row in data:
        if row['contract_id']=='S':
            r=deepcopy(row);r['contract_id']='T';r['record_id']='T-'+r['record_id']
            if r['row_type']=='contract':r['underlying_id']='T'
            if r['record_id']=='T-end-S' and action=='split':r['bid']=r['ask']='60'
            if not (missing_quote and r['record_id']=='T-q-S-1'):extra.append(r)
    data+=extra
    adjusted=deepcopy(next(r for r in extra if r['row_type']=='contract'))
    adjusted.update(record_id='adjusted-T',timestamp=at,effective_at=at,known_at=at,adjustment_id='extra-action',lot_size='20' if action=='split' else '10')
    data.append(adjusted)
    data.append(dict(row_type='corporate_action',record_id='extra-action',contract_id='T',timestamp=at,effective_at=at,known_at=at,source='synthetic-test',action=action,adjustment_id='extra-action',adjusted_contract_ids='T',**({'ratio':'2'} if action=='split' else {'amount':'2'})))
    decl=declaration().model_dump(mode='json');decl['expected_intervals'].append(dict(contract_id='T',start=D,end=F,interval_seconds=60))
    return parse_history(csv_bytes(data),'csv',ImportDeclaration(**decl))

@pytest.mark.parametrize('action,cash,quantity',[('cash_dividend','3167','10'),('split','3147','20')])
def test_unselected_initial_holdings_actions_are_accounted(action,cash,quantity):
    r=request(mode='owned',initial_inventory=[dict(contract_id=id,quantity=10,acquisition_cost_per_unit='95') for id in ['S','T']])
    report=run_backtest(unselected_owned_dataset(action),r)
    assert report['cash']==cash;assert report['inventory']['T']==quantity
    assert report['equity_curve'][-1]['equity']==str(int(cash)+1200)

def test_unselected_initial_holding_quote_gap_fails_closed():
    r=request(mode='owned',initial_inventory=[dict(contract_id=id,quantity=10,acquisition_cost_per_unit='95') for id in ['S','T']])
    with pytest.raises(ValueError,match='unsupported_period_quote_gap'):
        run_backtest(unselected_owned_dataset('cash_dividend',missing_quote=True),r)

def test_owned_split_before_entry_persists_adjusted_basis_on_restart():
    import json
    from copy import deepcopy
    from app.terminal.options_backtest import HistoricalEngine
    data=deepcopy(action_dataset('split')['rows'])
    decision='2026-01-03T09:00:00+05:30';fill='2026-01-03T09:01:00+05:30'
    for id in ['S','C']:
        template=next(r for r in data if r['row_type']=='quote' and r['contract_id']==id)
        for i,t in enumerate([decision,fill]):
            row=deepcopy(template);row.update(record_id=f'after-split-{id}-{i}',timestamp=t,effective_at=t,known_at=t,bid='49' if id=='S' else '2.5',ask='50' if id=='S' else '3',bid_quantity='20',ask_quantity='20');data.append(row)
    decl=declaration().model_dump(mode='json')
    decl['expected_intervals']+=[dict(contract_id=id,start=decision,end=fill,interval_seconds=60) for id in ['S','C']]
    parsed=parse_history(csv_bytes(data),'csv',ImportDeclaration(**decl))
    r=request(mode='owned',initial_inventory=[dict(contract_id='S',quantity=10,acquisition_cost_per_unit='95')],entries=[dict(decision_at=decision,stock_contract_id='S',call_contract_id='C',quantity=20)])
    engine=HistoricalEngine(parsed,r);state=engine.initial
    while engine.events[state['cursor']]['kind']!='action':state=engine.step(state)
    state=engine.step(state)
    # This durable field must be adjusted even with no currently open position.
    assert state['initial_basis']['S']=='47.5'
    resumed=HistoricalEngine(parsed,r);state=json.loads(json.dumps(state))
    while state['cursor']<len(resumed.events):state=resumed.step(state)
    result=resumed.report(state)
    assert result['cash']=='3146'
    assert result['attribution'][0]['realised_profit']=='196'
    assert result['attribution'][0]['expiry_expected_profit']=='196'
