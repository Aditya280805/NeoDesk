from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
import pytest
from pydantic import ValidationError
from app.terminal.options_market_contracts import MarketContract, MarketQuote, StrategyMarketEvidence
from app.terminal.options_strategy_contracts import StrategyRequest
from app.terminal.options_strategies import analyze_strategy

NOW = datetime(2026, 11, 1, tzinfo=UTC)

def fixture(kind='covered_call', **updates):
    contracts = tuple(MarketContract(instrument_id=id, underlying_id='stock', kind=k,
        expiry=None if k=='equity' else (NOW+timedelta(days=30)).date(), strike=strike,
        lot_size=100, identity_verified=True, settlement_verified=True,
        settlement_rule_version='fixture-rule-001', basis='synthetic verified stock fixture',
        provenance=('synthetic fixture settlement rule; not exchange certification',))
        for id,k,strike in [('stock','equity',None),('call','call','110'),('put','put','90')])
    quotes=tuple(MarketQuote(contract_id=id,observed_at=NOW,exchange_timestamp=NOW,bid=bid,ask=ask,
        bid_quantity='100',ask_quantity='100',source='fixture',provenance=('fixture',))
        for id,bid,ask in [('stock','100','100'),('call','5','5'),('put','2','2')])
    ev=StrategyMarketEvidence(observed_at=NOW,contracts=contracts,quotes=quotes,source='fixture',completeness='complete')
    args=dict(kind=kind,mode='hypothetical',stock_contract_id='stock',call_contract_id='call',
        put_contract_id='put' if kind=='collar' else None,quantity=100,evidence_id=ev.evidence_id,
        quote_max_age_seconds=60,costs=dict(opening_fees_inr='10',expiry_fees_inr='0',stock_slippage_per_unit='0',call_slippage_per_unit='0',put_slippage_per_unit='0'))
    args.update(updates)
    return StrategyRequest(**args),ev

@pytest.mark.parametrize('kind,profits,breakeven', [('covered_call',['-9510','490','1490','1490'],'95.1'),('collar',['-710','290','1290','1290'],'97.1')])
def test_exact_payoffs(kind,profits,breakeven):
    req,ev=fixture(kind)
    report=analyze_strategy(req,ev,None,NOW)
    assert [report.current_basis.profit_at(Decimal(s)) for s in ['0','100','110','120']]==list(map(Decimal,profits))
    assert report.current_basis.breakevens==(Decimal(breakeven),)
    assert report.status=='eligible'
    assert report.horizon_days==30
    assert report.current_capital==Decimal('9510' if kind=='covered_call' else '9710')
    assert report.costs.total_inr==10
    assert report.broker_margin is None
    assert 'user-supplied' in ' '.join(report.limitations)
    with localcontext() as ctx:
        ctx.prec=3
        assert analyze_strategy(req,ev,None,NOW).current_basis.max_profit==report.current_basis.max_profit

@pytest.mark.parametrize('change,reason', [({'quantity':99},'lot_multiple'),({'costs':{}},'costs_missing'),({'quote_max_age_seconds':1},'quote_stale')])
def test_fail_closed(change,reason):
    req,ev=fixture(**change)
    result=analyze_strategy(req,ev,None,NOW+timedelta(seconds=2))
    assert result.status!='eligible'
    assert reason in result.reasons

def test_owned_requires_server_holding_and_preserves_basis():
    from app.terminal.options_strategy_contracts import HoldingEvidence
    req,ev=fixture(mode='owned',holding_row_id='h',acquisition_cost_per_share='20')
    assert analyze_strategy(req,ev,None,NOW).status=='cannot_assess'
    holding=HoldingEvidence(row_id='h',stock_contract_id='stock',underlying_id='stock',available_quantity='100',
        acquisition_cost_per_share='80',observed_at=NOW,evidence_id=ev.evidence_id,identity_verified=True,coverage_verified=True)
    result=analyze_strategy(req,ev,(holding,),NOW)
    assert result.acquisition_basis.stock_basis==80
    assert result.current_basis.stock_basis==100
    assert result.request.acquisition_cost_per_share==20

@pytest.mark.parametrize('updates', [{'quantity':True},{'quantity':1.5},{'identity_verified':True},{'acquisition_cost_per_share':'NaN'},{'costs':{'opening_fees_inr':'-1'}}])
def test_invalid_request(updates):
    with pytest.raises(ValidationError): fixture(**updates)

def test_metadata_quote_and_margin_gates():
    req,ev=fixture(criteria={'require_broker_margin':True})
    assert 'broker_margin_unavailable' in analyze_strategy(req,ev,None,NOW).reasons
    raw=ev.model_dump(); raw['contracts'][1]['settlement_verified']=False
    assert 'settlement_unverified' in analyze_strategy(req,StrategyMarketEvidence(**raw),None,NOW).reasons
    raw=ev.model_dump(); raw['quotes'][1]['bid']=None
    assert 'quote_missing' in analyze_strategy(req,StrategyMarketEvidence(**raw),None,NOW).reasons

@pytest.mark.parametrize('path,value,reason', [
    ('identity_verified',False,'underlying_unverified'),('lot_size',None,'lot_unverified'),
    ('settlement_rule_version','unsupported','settlement_unverified'),('underlying_id','other','underlying_unverified')])
def test_unverified_contract_metadata(path,value,reason):
    req,ev=fixture();raw=ev.model_dump();raw['contracts'][1][path]=value
    if path=='identity_verified': raw['contracts'][1]['settlement_verified']=False
    if path=='lot_size':
        raw['contracts'][1]['identity_verified']=False;raw['contracts'][1]['settlement_verified']=False
    assert reason in analyze_strategy(req,StrategyMarketEvidence(**raw),None,NOW).reasons

@pytest.mark.parametrize('path,value,reason', [
    ('bid_quantity',None,'quote_size_unverified'),('bid_quantity','99','quote_size_shortfall'),
    ('exchange_timestamp',None,'exchange_time_unverified'),
    ('observed_at',NOW+timedelta(seconds=1),'quote_future'),
    ('exchange_timestamp',NOW+timedelta(seconds=1),'exchange_time_invalid'),
    ('observed_at',NOW-timedelta(seconds=61),'quote_stale')])
def test_unusable_quotes(path,value,reason):
    req,ev=fixture();raw=ev.model_dump();raw['quotes'][1][path]=value
    report=analyze_strategy(req,StrategyMarketEvidence(**raw),None,NOW)
    assert report.status!='eligible';assert reason in report.reasons

@pytest.mark.parametrize('value',['NaN','Infinity','-1',True,'1e30'])
def test_nonfinite_or_invalid_quotes(value):
    req,ev=fixture();raw=ev.model_dump();raw['quotes'][1]['bid']=value
    with pytest.raises(ValidationError): StrategyMarketEvidence(**raw)

def test_crossed_quotes_rejected():
    _,ev=fixture();raw=ev.model_dump();raw['quotes'][1]['bid']='6'
    with pytest.raises(ValidationError): StrategyMarketEvidence(**raw)

def test_collar_extrema_costs_criteria_and_wire():
    req,ev=fixture('collar',costs={'opening_fees_inr':'3','expiry_fees_inr':'7',
        'stock_slippage_per_unit':'.1','call_slippage_per_unit':'.2','put_slippage_per_unit':'.3'})
    report=analyze_strategy(req,ev,None,NOW)
    assert report.costs.slippage_inr==60
    assert report.costs.total_inr==70
    assert report.current_capital==9763
    assert report.current_basis.max_profit==1230
    assert report.current_basis.min_profit==-770
    assert report.current_basis.maximum_loss==770
    assert report.current_basis.breakevens==(Decimal('97.7'),)
    assert report.current_basis.horizon_yield==Decimal(1230)/Decimal(9763) or str(report.current_basis.horizon_yield).startswith('0.1259858')
    wire=report.model_dump(mode='json')
    assert wire['costs']['total_inr']=='70'; assert wire['broker_margin'] is None
    req=req.model_copy(update={'criteria':req.criteria.model_copy(update={'maximum_loss_inr':Decimal('700')})})
    assert 'maximum_loss_limit' in analyze_strategy(req,ev,None,NOW).reasons

def test_missing_costs_preserves_gross_only():
    req,ev=fixture(costs={}); report=analyze_strategy(req,ev,None,NOW)
    assert report.gross_current_basis.profit_at(Decimal(110))==1500
    assert report.current_basis is None and report.current_capital is None

@pytest.mark.parametrize('available,coverage,reason',[('99',True,'holding_shortfall'),(None,True,'holding_quantity_missing'),('100',False,'holding_coverage_unverified')])
def test_owned_available_quantity_proof(available,coverage,reason):
    from app.terminal.options_strategy_contracts import HoldingEvidence
    req,ev=fixture(mode='owned',holding_row_id='h')
    h=HoldingEvidence(row_id='h',stock_contract_id='stock',underlying_id='stock',available_quantity=available,
        observed_at=NOW,evidence_id=ev.evidence_id,identity_verified=True,coverage_verified=coverage)
    assert reason in analyze_strategy(req,ev,(h,),NOW).reasons

def test_collar_invalid_strike_and_expiry():
    req,ev=fixture('collar');raw=ev.model_dump();raw['contracts'][2]['strike']='120'
    assert 'put_above_call' in analyze_strategy(req,StrategyMarketEvidence(**raw),None,NOW).reasons
    raw=ev.model_dump();raw['contracts'][2]['expiry']=(NOW+timedelta(days=31)).date()
    assert 'expiry_mismatch' in analyze_strategy(req,StrategyMarketEvidence(**raw),None,NOW).reasons

def test_wrong_selected_leg_fails_closed_instead_of_crashing():
    req,ev=fixture()
    raw=ev.model_dump(); raw['contracts'][1].update(kind='equity',expiry=None,strike=None)
    report=analyze_strategy(req,StrategyMarketEvidence(**raw),None,NOW)
    assert report.status=='ineligible'
    assert 'leg_type_invalid' in report.reasons
    assert report.current_basis is None

def test_ambient_traps_rounding_are_isolated():
    from decimal import Inexact,ROUND_DOWN
    req,ev=fixture('collar');normal=analyze_strategy(req,ev,None,NOW)
    with localcontext() as ctx:
        ctx.prec=2;ctx.rounding=ROUND_DOWN;ctx.traps[Inexact]=True
        other=analyze_strategy(req,ev,None,NOW)
        assert other.current_basis==normal.current_basis
        assert other.current_basis.profit_at(Decimal('100.123'))==Decimal('302.3')

def test_expiry_horizon_uses_india_calendar():
    req,ev=fixture()
    now=datetime(2026,11,1,20,tzinfo=UTC)
    report=analyze_strategy(req,ev,None,now)
    assert report.horizon_days==29

@pytest.mark.parametrize('version',['non-European-non-physical.v1','European-physical-unknown.v9','opaque-unregistered-0007'])
def test_settlement_identifier_never_implies_semantics(version):
    req,ev=fixture();raw=ev.model_dump()
    for contract in raw['contracts'][1:]:contract['settlement_rule_version']=version
    report=analyze_strategy(req,StrategyMarketEvidence(**raw),None,NOW)
    assert report.status=='cannot_assess'
    assert 'settlement_unverified' in report.reasons

def synthetic_rule_evidence(ev,*,source='fixture',provenance=('synthetic fixture settlement rule; not exchange certification',)):
    raw=ev.model_dump();raw['source']=source
    for contract in raw['contracts'][1:]:
        contract['settlement_rule_version']='fixture-rule-001'
        contract['provenance']=provenance
    return StrategyMarketEvidence(**raw)

def test_exact_opaque_supported_fixture_rule_has_explicit_semantics():
    req,ev=fixture();report=analyze_strategy(req,synthetic_rule_evidence(ev),None,NOW)
    assert report.status=='eligible'
    assert any('synthetic' in text.lower() and 'exchange certification' in text.lower() for text in report.limitations)

@pytest.mark.parametrize('source,provenance',[
    ('kotak',('synthetic fixture settlement rule; not exchange certification',)),
    ('fixture',('provider claims NSE rule',)),
])
def test_synthetic_registry_rule_cannot_certify_broker_data(source,provenance):
    req,ev=fixture();report=analyze_strategy(req,synthetic_rule_evidence(ev,source=source,provenance=provenance),None,NOW)
    assert report.status=='cannot_assess'
    assert 'settlement_unverified' in report.reasons
