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
