from datetime import UTC, datetime
import json
import pytest
from pydantic import ValidationError
from app.terminal.options_market_contracts import MarketContract, MarketQuote, StrategyMarketEvidence
from app.terminal import options_readiness as readiness

STAMP = datetime(2026, 11, 1, tzinfo=UTC)
def contract(**changes):
    return MarketContract(**(dict(instrument_id='123', underlying_id='456', kind='call', expiry='2026-11-26', strike='100', lot_size=10, basis='fixture', provenance=('fixture',)) | changes))
def quote(**changes):
    return MarketQuote(**(dict(contract_id='123', observed_at=STAMP, source='fixture', provenance=('fixture',)) | changes))
def test_null_zero_and_strings():
    q = quote(last='0')
    assert q.last == 0 and q.bid is None
    assert json.loads(q.model_dump_json())['last'] == '0'
@pytest.mark.parametrize('value', [True, 'NaN', 'Infinity', '-1', '1e19', '0.'+'1'*100])
def test_invalid_numbers(value):
    with pytest.raises(ValidationError): quote(last=value)
def test_time_crossed_and_contract_rules():
    for changes in ({'observed_at':datetime(2026,1,1)}, {'exchange_timestamp':datetime(2026,1,1)}, {'bid':'2','ask':'1'}):
        with pytest.raises(ValidationError): quote(**changes)
    for changes in ({'lot_size':True}, {'lot_size':0}, {'settlement_verified':True}, {'expiry':None}):
        with pytest.raises(ValidationError): contract(**changes)
def test_evidence_bounds_and_identity():
    base=dict(observed_at=STAMP, source='fixture', completeness='partial')
    for changes in (dict(contracts=(contract(),contract(strike='101'))), dict(quotes=(quote(),)), dict(contracts=(contract(),),quotes=(quote(),quote(last='2'))), dict(contracts=(contract(),)*501)):
        with pytest.raises(ValidationError): StrategyMarketEvidence(**base, **changes)
    evidence=StrategyMarketEvidence(**base,contracts=(contract(),),quotes=(quote(),))
    other=contract(instrument_id='124')
    other_quote=quote(contract_id='124',last='1.00')
    left=StrategyMarketEvidence(**base,evidence_id=evidence.evidence_id,contracts=(contract(),other),quotes=(quote(),other_quote))
    right=StrategyMarketEvidence(**base,evidence_id=evidence.evidence_id,contracts=(other,contract()),quotes=(other_quote,quote()))
    assert left.canonical_json()==right.canonical_json()
    serialized=json.loads(left.canonical_json())
    assert serialized['quotes'][0]['last'] is None
    assert serialized['quotes'][1]['last']=='1'
    assert serialized['contracts'][0]['strike']=='100'
    with pytest.raises(ValidationError): evidence.source='changed'
def test_default_local_and_unknown(monkeypatch,capsys):
    monkeypatch.setattr(readiness,'run_live_check',lambda *a:pytest.fail('network'))
    assert readiness.main([])==0
    result=json.loads(capsys.readouterr().out)
    assert result['fields'] and readiness.get_data_capabilities().status_for('unknown')=='unverified'
def test_explicit_live_sanitizes(monkeypatch,capsys):
    async def failed(*a): raise ValueError('secret-token')
    monkeypatch.setattr(readiness,'_delegate_live',failed)
    assert readiness.main(['--mode','live-model'])==1
    output=capsys.readouterr().out
    assert 'secret-token' not in output and 'unavailable' in output
def test_legacy_chain_compatibility():
    from test_options_agent import chain
    from app.terminal.options_snapshot import normalize_snapshot, OptionsContext
    snapshot=normalize_snapshot(chain(),OptionsContext())
    evidence=readiness.legacy_chain_to_evidence(snapshot)
    assert snapshot['rows'][0]['ltp'] is not None
    assert evidence.contracts and evidence.quotes and evidence.completeness=='partial'
    assert all(c.lot_size is None and c.underlying_id is None and not c.identity_verified for c in evidence.contracts)
    assert all(q.bid is None and q.ask is None for q in evidence.quotes)

def test_documented_quote_adapter_and_exact_tokens():
    row=dict(exchange='nse_fo',exchange_token='123',ltp='5',last_volume='0',open_int='4',
             depth={'buy':[{'price':'4','quantity':'10'}], 'sell':[{'price':'6','quantity':'20'}]})
    evidence=readiness.quotes_to_evidence([row],(contract(),),STAMP)
    assert evidence.quotes[0].bid==4 and evidence.quotes[0].ask_quantity==20
    assert evidence.quotes[0].exchange_timestamp is None
    row['exchange_token']='wrong'
    with pytest.raises(ValueError): readiness.quotes_to_evidence([row],(contract(),),STAMP)

def test_catalogue_matching_and_bounded_acquisition():
    from test_options_agent import chain
    from app.terminal.options_snapshot import normalize_snapshot, OptionsContext
    snapshot=normalize_snapshot(chain(),OptionsContext())
    row=snapshot['rows'][0]
    catalogue=[dict(id='nse_fo|123',token='123',exchange='nse_fo',kind='OPTION',symbol=row['symbol'],expiry='2026-10-29',strike=row['strike'],option_type='CE' if row['side']=='CALL' else 'PE',lot_size=50)]
    evidence=readiness.legacy_chain_to_evidence(snapshot,catalogue=catalogue)
    assert evidence.contracts[0].instrument_id=='nse_fo|123'
    assert evidence.contracts[0].lot_size is None and not evidence.contracts[0].identity_verified
    catalogue[0]['source_metadata']={'source':'kotak-scrip-master','lLotSize':'50'}
    assert readiness.legacy_chain_to_evidence(snapshot,catalogue=catalogue).contracts[0].lot_size==50
    with pytest.raises(ValueError): readiness.legacy_chain_to_evidence(snapshot,catalogue=catalogue*2)

def test_acquisition_preserves_absent_quote_fields():
    from test_options_agent import chain
    from app.terminal.options_snapshot import normalize_snapshot, OptionsContext
    context=OptionsContext()
    row=normalize_snapshot(chain(),context)['rows'][0]
    catalogue=[dict(id='nse_fo|123',token='123',exchange='nse_fo',kind='OPTION',symbol=row['symbol'],expiry='2026-10-29',strike=row['strike'],option_type='CE' if row['side']=='CALL' else 'PE',lot_size=50)]
    class Store:
        def search(self, **kwargs): return {'items':catalogue,'total':1}
    class Market:
        calls=[]
        def session_generation(self,user_id): return 'fixture-session'
        def call(self,method,**kwargs):
            self.calls.append((method,kwargs))
            return chain() if method=='option_chain' else [dict(exchange='nse_fo',exchange_token='123',ltp='5')]
    market=Market()
    evidence=readiness.fetch_strategy_market_evidence(market,Store(),42,context,deadline=123)
    assert [call[0] for call in market.calls]==['option_chain','quotes']
    assert all(call[1]['user_id']==42 and call[1]['deadline_monotonic']==123 for call in market.calls)
    result=next(q for q in evidence.quotes if q.contract_id=='nse_fo|123')
    assert result.last==5 and result.bid is None and result.volume is None

@pytest.mark.parametrize('enrich',[False,True])
def test_acquisition_rejects_session_change(enrich):
    from test_options_agent import chain
    from app.terminal.options_snapshot import normalize_snapshot, OptionsContext
    context=OptionsContext()
    row=normalize_snapshot(chain(),context)['rows'][0]
    catalogue=[dict(id='nse_fo|123',token='123',exchange='nse_fo',kind='OPTION',symbol=row['symbol'],expiry='2026-10-29',strike=row['strike'],option_type='CE' if row['side']=='CALL' else 'PE')]
    class Store:
        def search(self,**kwargs):
            if not enrich: market.generation='reconnected'
            return {'items':catalogue if enrich else []}
    class Market:
        generation='first'
        def session_generation(self,user_id):
            assert user_id==42
            return self.generation
        def call(self,method,**kwargs):
            if method=='quotes': self.generation='reconnected'
            return chain() if method=='option_chain' else [dict(exchange='nse_fo',exchange_token='123',ltp='5')]
    market=Market()
    with pytest.raises(ValueError,match='session changed'):
        readiness.fetch_strategy_market_evidence(market,Store(),42,context)

def test_master_retains_raw_lot_provenance():
    from app.terminal.market import parse_master
    rows=parse_master('pSymbol,pTrdSymbol,pInstType,lLotSize\n123,ABC,OPTSTK,50\n124,DEF,OPTSTK,\n','nse_fo')
    assert rows[0]['source_metadata']['lLotSize']=='50'
    assert rows[1]['source_metadata']['lLotSize']==''
    assert rows[1]['lot_size']==1  # Legacy catalogue compatibility.
