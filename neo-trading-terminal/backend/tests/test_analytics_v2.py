from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_routing_rejects_mismatched_or_duplicate_stages():
    from app.terminal.analytics_contracts import RoutingDecision
    with pytest.raises(ValidationError):
        RoutingDecision(mode='SINGLE_OPTIONS', delegated_agents=['portfolio_risk'])
    with pytest.raises(ValidationError):
        RoutingDecision(mode='COMPOSITE_PIPELINE', delegated_agents=['portfolio_risk', 'portfolio_risk'])
    assert RoutingDecision(mode='SINGLE_OPTIONS', delegated_agents=['options_trading_analysis']).delegated_agents == ('options_trading_analysis',)


def test_daily_vix_zscore_does_not_use_twenty_intraday_samples():
    from datetime import timedelta
    from app.terminal.quant_technical import technical_regime
    start = datetime(2026,1,1,4,tzinfo=UTC)
    bars = [dict(time=(start+timedelta(minutes=i)).isoformat(),open=100+i,high=102+i,low=99+i,close=101+i,volume=10) for i in range(40)]
    values = [15+i/10 for i in range(40)]
    result = technical_regime(bars,vix_history=values)
    assert result['metrics']['india_vix']==values[-1]
    assert result['metrics']['vix_zscore20'] is None
    assert result['regime']=='UNAVAILABLE'
    assert result['unavailable_reasons']['vix_zscore20']=='daily_vix_basis_not_established'
    daily = [{**bar,'time':(start+timedelta(days=i)).isoformat()} for i,bar in enumerate(bars)]
    assert technical_regime(daily,vix_history=values)['metrics']['vix_zscore20'] is not None


def test_proposals_require_verified_lot_multiples():
    from app.terminal.analytics_contracts import StrategyProposal
    data = dict(proposal_id=uuid4(), evidence_id=uuid4(), template='bull_call_spread',
                valued_at=datetime.now(UTC), legs=[dict(contract_id='NIFTY-CALL', expiry='2026-11-17',
                side='BUY', quantity=26, lot_size=25, strike='25000', option_type='CALL')])
    with pytest.raises(ValidationError):
        StrategyProposal(**data)


def test_sanitizer_keeps_precision_and_replaces_nonfinite():
    from app.terminal.analytics_contracts import sanitize_quant_payload
    assert sanitize_quant_payload({'x': [float('nan'), float('inf'), 0.123456789]}) == {'x': [None, None, 0.123456789]}


def test_evidence_storage_is_owner_bound_and_append_only(tmp_path):
    from app.terminal.analytics_store import AnalyticsStore
    store = AnalyticsStore(tmp_path / 'analytics.sqlite3')
    key = str(uuid4())
    store.capture(7, key, '2026-11-11T10:00:00+00:00', {'price': 12})
    assert store.read(7, key)['price'] == 12
    assert store.read(8, key) is None
    with pytest.raises(ValueError):
        store.capture(7, key, '2026-11-11T10:00:00+00:00', {'price': 13})


def test_budget_is_shared_across_connections_and_retains_cancelled_capacity():
    import asyncio
    from app.terminal.analytics_runtime import TurnBudget, BoundedWork

    async def scenario():
        budget = TurnBudget()
        budget.consume('portfolio_analysis')
        budget.consume('portfolio_analysis')
        with pytest.raises(ValueError):
            budget.consume('portfolio_analysis')
        gate = BoundedWork(capacity=1)
        finished = asyncio.Event()
        async def slow():
            await finished.wait()
            return 1
        caller = asyncio.create_task(gate.run(7, slow))
        await asyncio.sleep(0)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        with pytest.raises(ValueError):
            await gate.run(8, slow)
        finished.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not gate.pending
    asyncio.run(scenario())


def test_black76_put_call_parity_and_greeks():
    from app.terminal.quant_pricing import black76, implied_volatility
    import math
    call = black76(100, 100, .5, .2, .05, 'CALL')
    put = black76(100, 100, .5, .2, .05, 'PUT')
    assert call['price'] == pytest.approx(5.49801487)
    assert call['price'] - put['price'] == pytest.approx(0)
    assert implied_volatility(call['price'], 100, 100, .5, .05, 'CALL') == pytest.approx(.2)
    h = .0001
    up = black76(100, 100, .5, .2+h, .05, 'CALL')
    down = black76(100, 100, .5, .2-h, .05, 'CALL')
    assert call['vanna'] == pytest.approx((up['delta_forward']-down['delta_forward'])/(2*h), rel=1e-5)
    assert call['volga'] == pytest.approx((up['vega_per_unit']-down['vega_per_unit'])/(2*h), rel=1e-5)
    assert black76(110, 100, 0, .2, .05, 'CALL')['price'] == 10
    assert black76(110, 100, 0, .2, .05, 'CALL')['gamma_forward'] is None
    with pytest.raises(ValueError):
        black76(math.nan, 100, .5, .2, .05, 'CALL')


@pytest.mark.parametrize('count,available95,available99', [(249,False,False),(250,True,False),(999,True,False),(1000,True,True)])
def test_tail_availability_is_independent(count, available95, available99):
    from app.terminal.quant_risk import historical_tail
    result = historical_tail(list(range(count)))
    assert (result['var_95'] is not None) == available95
    assert (result['cvar_95'] is not None) == available95
    assert (result['var_99'] is not None) == available99
    if available95 and not available99:
        assert result['unavailable_reasons']['cvar_99'] == 'insufficient_history_for_99pct'
    if available99:
        assert result['cvar_99'] >= result['var_99']


def test_stress_grid_survives_missing_historical_scenarios():
    from app.terminal.quant_risk import stress_matrix
    rows = [dict(kind='option', forward=100, spot=100, strike=100, iv=.2, tau=.1,
                 rate=.05, option_type='CALL', quantity=-25)]
    result = stress_matrix(rows)
    assert len(result['cells']) == 28
    assert result['historical_tail']['var_95'] is None
    assert result['max_stress_loss'] > 0


def test_cost_schedule_changes_by_trade_date_and_counts_buy_stamp():
    from app.terminal.indian_charges import statutory_charges
    from datetime import date
    old = statutory_charges('option','SELL',100000,date(2026,3,31))
    new = statutory_charges('option','SELL',100000,date(2026,4,1))
    assert old['stt_paise'] == 10000
    assert new['stt_paise'] == 15000
    assert statutory_charges('option','BUY',100000,date(2026,4,1))['stamp_paise'] == 300
    assert statutory_charges('option','EXERCISE',100000,date(2026,4,1))['stt_paise'] == 15000
    with pytest.raises(ValueError):
        statutory_charges('option','SELL',-100,date(2026,4,1))


def test_participant_csv_counts_are_not_delta():
    from app.terminal.nse_participant_flow import parse_participant_csv
    text = 'Participant wise Open Interest as on 11-Nov-2026\nClient Type,Future Index Long,Future Index Short,Option Index Call Long,Option Index Call Short,Option Index Put Long,Option Index Put Short\nFII,75,25,10,30,40,10\nDII,0,0,0,0,0,0\nPro,1,2,3,4,5,6\nClient,8,2,80,20,10,20\n'
    result = parse_participant_csv(text)
    assert result['participants']['FII']['index_futures_long_share'] == .75
    assert result['participants']['FII']['net_index_calls'] == -20
    assert result['participants']['DII']['index_futures_long_share'] is None
    assert result['unit'] == 'contracts'


def test_rising_squeeze_regime_rule_precedes_mean_reversion():
    from app.terminal.quant_technical import classify_regime
    assert classify_regime(21,1,30,adx_rise_3bars=4,prior_squeeze_percentile=10)=='HIGH_VOL_BREAKOUT'
    assert classify_regime(21,1,30,adx_rise_3bars=3,prior_squeeze_percentile=10)=='HIGH_VOL_MEAN_REVERTING'
    assert classify_regime(21,1,30,adx_rise_3bars=4,prior_squeeze_percentile=15)=='HIGH_VOL_MEAN_REVERTING'
    assert classify_regime(None,1,30)=='UNAVAILABLE'


def test_regulatory_unknown_inputs_do_not_pass():
    from app.terminal.quant_compliance import compliance_checks
    result = compliance_checks([{'contract_id':'x','quantity':25,'lot_size':25}], {})
    assert result['risk_verdict'] == 'CANNOT_ASSESS'
    result = compliance_checks([{'contract_id':'x','quantity':26,'lot_size':25}], {})
    assert result['risk_verdict'] == 'BREACH_HALT_REQUIRED'


def test_oi_partial_coverage_and_no_dealer_inventory_claim():
    from app.terminal.quant_microstructure import oi_microstructure
    result = oi_microstructure([dict(side='CALL',strike=100,open_interest=10,volume=2),dict(side='PUT',strike=100,open_interest=20,volume=3)])
    assert result['pcr_oi'] == 2
    assert result['max_pain_strike'] == 100
    assert result['dealer_gex_proxy'] is None
    assert result['rows'][0]['buildup'] is None


def test_analytics_mcp_scope_projection_and_shared_budget():
    import asyncio
    import time
    from unittest.mock import Mock
    from app.terminal.analytics_contracts import AnalyticsEvidence
    from app.terminal.analytics_runtime import TurnBudget
    from app.terminal.options_mcp import Capability, OptionsMCP
    from app.terminal.options_snapshot import OptionsContext
    async def scenario():
        evidence = AnalyticsEvidence(calculation_version='test.1',observed_at=None,retrieved_at=datetime.now(UTC),
                                     status='AVAILABLE',metrics={'pcr_oi':2})
        cap = Capability(7, OptionsContext(), 'run', time.monotonic()+30, session_generation='g')
        cap.bind_analytics({'get_nse_oi_microstructure':evidence},TurnBudget())
        collector = Mock()
        collector.assert_generation = Mock(return_value=None)
        runtime = OptionsMCP(Mock(),portfolio_service=collector)
        result = await runtime._read_analytics(cap,'get_nse_oi_microstructure')
        assert result['metrics']['pcr_oi'] == 2
        result['metrics']['pcr_oi'] = 100
        assert (await runtime._read_analytics(cap,'get_nse_oi_microstructure'))['metrics']['pcr_oi'] == 2
        with pytest.raises(ValueError):
            await runtime._read_analytics(cap,'get_nse_oi_microstructure')
        with pytest.raises(ValueError):
            cap.bind_analytics({'check_sebi_and_mwpl_compliance':evidence},TurnBudget())
    asyncio.run(scenario())


def test_technical_warmup_and_no_index_volume_fabrication():
    from app.terminal.quant_technical import technical_regime
    bars = [dict(open=100+i,high=102+i,low=99+i,close=101+i) for i in range(60)]
    result = technical_regime(bars, backend='numpy')
    assert result['metrics']['ema200'] is None
    assert result['metrics']['ema20'] is not None
    assert result['metrics']['vwap'] is None
    assert result['regime'] == 'UNAVAILABLE'
    assert 'ema200' in result['unavailable_reasons']


def test_surface_requires_history_and_uses_actual_expiry():
    from app.terminal.quant_surface import volatility_surface
    expiry = datetime(2026,11,17,10,tzinfo=UTC)
    now = datetime(2026,11,11,10,tzinfo=UTC)
    rows = [dict(contract_id='c',strike=100,side='CALL',iv=.2,expiry_at=expiry),
            dict(contract_id='p',strike=100,side='PUT',iv=.2,expiry_at=expiry)]
    result = volatility_surface(rows,forward=100,rate=.05,as_of=now)
    assert result['rows'][0]['tau'] == pytest.approx(6/365)
    assert result['atm_iv'] == .2
    assert result['iv_rank_252d'] is None


def test_attribution_rejects_inferred_portfolio_history():
    from app.terminal.quant_attribution import portfolio_attribution
    result = portfolio_attribution([])
    assert result['sharpe'] is None
    assert result['unavailable_reasons']['sharpe'] == 'insufficient_verified_return_history'


def test_source_revisions_preserve_old_data_and_block_date_mismatch(tmp_path):
    from app.terminal.analytics_sources import ParticipantReports
    from app.terminal.analytics_store import AnalyticsStore
    from datetime import date
    text = 'Participant wise Open Interest as on 11-Nov-2026\nClient Type,Future Index Long,Future Index Short,Option Index Call Long,Option Index Call Short,Option Index Put Long,Option Index Put Short\nFII,75,25,10,30,40,10\nDII,0,0,0,0,0,0\nPro,1,2,3,4,5,6\nClient,8,2,80,20,10,20\n'
    source = ParticipantReports(AnalyticsStore(tmp_path/'sources.sqlite3'))
    first = source.import_report(date(2026,11,11),text)
    second = source.import_report(date(2026,11,11),text.replace('75,25','70,30'))
    assert first['checksum'] != second['checksum']
    assert source.cached(date(2026,11,11),first['checksum'])['participants']['FII']['index_futures_long_share'] == .75
    with pytest.raises(ValueError):
        source.import_report(date(2026,11,10),text)


def test_continuation_owner_binding_replay_and_session_change(tmp_path):
    from app.terminal.analytics_continuation import Continuations
    from app.terminal.analytics_store import AnalyticsStore
    clock = [1000.]
    records = Continuations(AnalyticsStore(tmp_path/'resume.sqlite3'),clock=lambda:clock[0])
    binding = {'session':'g','policy':1,'context':'NIFTY','version':'v1'}
    key = records.start(7,binding,{'completed':[]})
    with pytest.raises(ValueError):
        records.claim(8,key,binding,'action')
    with pytest.raises(ValueError):
        records.claim(7,key,{**binding,'session':'new'},'action')
    claim = records.claim(7,key,binding,'action')
    assert claim['state'] == {'completed':[]}
    records.finish(7,key,'action',claim['lease_nonce'],{'completed':['options']},{'status':'partial'})
    assert records.claim(7,key,binding,'action')['replay'] == {'status':'partial'}
    clock[0] += 601
    with pytest.raises(ValueError):
        records.claim(7,key,binding,'new-action')


def test_candidates_are_prebound_and_selected_without_tool_call():
    from app.terminal.quant_proposals import candidate_proposals, select_proposal
    from datetime import date
    evidence_id = uuid4()
    contracts = [dict(contract_id=str(k),underlying_key='NIFTY',exchange='nse_fo',currency='INR',strike=k,option_type='CALL',expiry=date(2026,11,17),
                      lot_size=25,identity_verified=True) for k in (100,110)]
    candidates = candidate_proposals(contracts,evidence_id,datetime.now(UTC))
    assert len(candidates) == 1
    assert select_proposal(candidates,str(candidates[0].proposal_id),evidence_id) == candidates[0]
    with pytest.raises(ValueError):
        select_proposal(candidates,str(candidates[0].proposal_id),uuid4())
    assert not candidate_proposals([{**r,'identity_verified':False} for r in contracts],evidence_id,datetime.now(UTC))


def test_native_and_numpy_ema_and_bandwidth_parity():
    from app.terminal.quant_technical import technical_regime
    import math
    bars = [dict(open=100+math.sin(i),close=100+math.sin(i),high=102+math.sin(i),low=98+math.sin(i)) for i in range(250)]
    fallback = technical_regime(bars,backend='numpy')
    native = technical_regime(bars,backend='talib')
    assert native['metrics']['ema200'] == pytest.approx(fallback['metrics']['ema200'])
    assert native['metrics']['bbands_width'] == pytest.approx(fallback['metrics']['bbands_width'])


@pytest.mark.parametrize('row',[dict(kind='equity',spot=100,quantity=float('nan')),
                               dict(kind='typo',spot=100,quantity=1),
                               dict(kind='equity',spot=-100,quantity=1)])
def test_stress_rejects_invalid_positions(row):
    from app.terminal.quant_risk import stress_matrix
    with pytest.raises(ValueError):
        stress_matrix([row])


def test_surface_cannot_share_single_forward_across_expiries():
    from app.terminal.quant_surface import volatility_surface
    now = datetime(2026,11,11,10,tzinfo=UTC)
    rows = [dict(contract_id=str(day),strike=100,side='CALL',iv=.2,expiry_at=datetime(2026,11,day,10,tzinfo=UTC)) for day in (17,24)]
    with pytest.raises(ValueError):
        volatility_surface(rows,forward=100,rate=.05,as_of=now)


def test_old_continuation_worker_cannot_finish_reclaimed_action(tmp_path):
    from app.terminal.analytics_continuation import Continuations
    from app.terminal.analytics_store import AnalyticsStore
    clock = [1000.]
    records = Continuations(AnalyticsStore(tmp_path/'fencing.sqlite3'),clock=lambda:clock[0])
    key = records.start(7,{'session':'g'},{})
    old = records.claim(7,key,{'session':'g'},'a')
    clock[0] += 36
    new = records.claim(7,key,{'session':'g'},'a')
    with pytest.raises(ValueError):
        records.finish(7,key,'a',old['lease_nonce'],{}, {'stale':True})
    records.finish(7,key,'a',new['lease_nonce'],{}, {'valid':True})


def test_spread_proposal_requires_two_distinct_ordered_legs():
    from app.terminal.analytics_contracts import StrategyProposal
    leg = dict(contract_id='x',underlying_key='NIFTY',exchange='nse_fo',currency='INR',expiry='2026-11-17',side='BUY',quantity=25,lot_size=25,strike=100,option_type='CALL')
    with pytest.raises(ValidationError):
        StrategyProposal(evidence_id=uuid4(),template='bull_call_spread',valued_at=datetime.now(UTC),legs=[leg])
    with pytest.raises(ValidationError):
        StrategyProposal(evidence_id=uuid4(),template='bull_call_spread',valued_at=datetime.now(UTC),legs=[leg,{**leg,'side':'SELL'}])


def test_stale_analytics_discovery_is_denied_without_consuming_tool_budget():
    import asyncio
    import time
    from unittest.mock import Mock
    from app.terminal.analytics_contracts import AnalyticsEvidence
    from app.terminal.analytics_runtime import TurnBudget
    from app.terminal.options_mcp import Capability, OptionsMCP
    from app.terminal.options_snapshot import OptionsContext
    async def scenario():
        cap = Capability(7,OptionsContext(),'run',time.monotonic()+30,session_generation='old')
        budget = TurnBudget()
        cap.bind_analytics({'get_nse_oi_microstructure':AnalyticsEvidence(calculation_version='v1',observed_at=None,
                           retrieved_at=datetime.now(UTC),status='PARTIAL',metrics={})},budget)
        collector = Mock()
        collector.assert_generation = Mock(side_effect=ValueError('stale session'))
        runtime = OptionsMCP(Mock(),portfolio_service=collector)
        with pytest.raises(ValueError):
            await runtime._validate_analytics_discovery(cap)
        assert not budget.calls
        with pytest.raises(ValueError):
            await runtime._read_analytics(cap,'get_nse_oi_microstructure')
    asyncio.run(scenario())


def test_historical_full_repricing_keeps_95_when_99_unavailable():
    from app.terminal.quant_risk import historical_repricing
    from datetime import date, timedelta
    positions = [dict(contract_id='a',kind='option',forward=100,spot=100,strike=100,iv=.2,tau=.1,rate=.05,option_type='CALL',quantity=25)]
    history = {'a':[dict(session=i,date=(date(2020,1,1)+timedelta(days=i)).isoformat(),spot=100+i/100,iv=.2+i/100000) for i in range(501)]}
    result = historical_repricing(positions,history)
    for horizon in ('1d','5d'):
        assert result['portfolio'][horizon]['cvar_95'] is not None
        assert result['portfolio'][horizon]['cvar_99'] is None
    history['a'][100]['iv'] = None
    result = historical_repricing(positions,history)
    assert result['instruments']['a']['1d']['scenario_count'] == 498


def test_debit_spread_gross_payoff_and_no_false_net_cost_claim():
    from app.terminal.quant_proposals import candidate_proposals, spread_payoff
    from datetime import date
    contracts = [dict(contract_id=str(k),underlying_key='NIFTY',exchange='nse_fo',currency='INR',strike=k,option_type='CALL',expiry=date(2026,11,17),lot_size=25,identity_verified=True) for k in (100,110)]
    p = candidate_proposals(contracts,uuid4(),datetime.now(UTC))[0]
    result = spread_payoff(p,{'100':{'bid':11,'ask':12},'110':{'bid':5,'ask':6}})
    assert result['gross_max_loss_paise'] == 17500
    assert result['gross_max_profit_paise'] == 7500
    assert result['net_max_profit_paise'] is None
    assert result['gross_breakeven'] == '107'


def test_all_macro_tools_return_versioned_unavailable_evidence_without_inputs():
    from app.terminal.analytics_engine import calculate_evidence
    from app.terminal.analytics_runtime import TOOLS_BY_ROLE
    for name in set().union(*TOOLS_BY_ROLE.values()):
        result = calculate_evidence(name,{},source_refs=(),observed_at=None)
        assert result.status == 'UNAVAILABLE'
        assert result.unavailable_reasons


def test_macro_payload_keeps_candidates_without_new_tool():
    from app.terminal.analytics_engine import calculate_evidence
    from app.terminal.quant_proposals import candidate_proposals
    from datetime import date
    candidates = candidate_proposals([dict(contract_id=str(k),underlying_key='NIFTY',exchange='nse_fo',currency='INR',strike=k,option_type='CALL',expiry=date(2026,11,17),lot_size=25,identity_verified=True) for k in (100,110)],uuid4(),datetime.now(UTC))
    evidence = calculate_evidence('get_nse_oi_microstructure',{'chain_rows':[dict(side='CALL',strike=100,open_interest=10),dict(side='PUT',strike=100,open_interest=20)]},source_refs=('snapshot-id',),observed_at=None,candidates=candidates,evidence_id=candidates[0].evidence_id)
    assert evidence.metrics['pcr_oi'] == 2
    assert evidence.candidate_proposals == candidates


def test_candidate_spreads_cannot_mix_underlyings():
    from app.terminal.quant_proposals import candidate_proposals
    from datetime import date
    contracts = [dict(contract_id=str(k),underlying_key=u,exchange='nse_fo',currency='INR',strike=k,
                      option_type='CALL',expiry=date(2026,11,17),lot_size=25,identity_verified=True)
                 for k,u in ((100,'NIFTY'),(110,'OTHER'))]
    assert not candidate_proposals(contracts,uuid4(),datetime.now(UTC))


def test_hrp_excludes_non_cash_assets_and_normalizes_weights():
    import pandas as pd
    import numpy as np
    from app.terminal.quant_attribution import hrp_weights
    i = np.arange(60)
    prices = pd.DataFrame({'a':100+i*.1+np.sin(i),'b':100+i*.15+np.cos(i),'option':100+i},index=pd.date_range('2020-01-01',periods=60))
    result = hrp_weights(prices,eligible_assets={'a','b'})
    assert set(result['weights']) == {'a','b'}
    assert sum(result['weights'].values()) == pytest.approx(1)
    assert result['excluded_assets'] == ['option']
