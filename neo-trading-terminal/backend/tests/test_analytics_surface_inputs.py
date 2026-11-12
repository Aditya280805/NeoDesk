import asyncio
from datetime import UTC,datetime,timedelta

import pytest

from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from app.terminal.quant_microstructure import gamma_exposure_proxy
from app.terminal.quant_pricing import black76
from test_analytics_capture import sources


def test_gex_scaling_sign_and_no_fabricated_flip():
    row = dict(forward=100,strike=100,tau=.2,iv=.2,rate=.05,side='CALL',open_interest=10,lot_size=25)
    result = gamma_exposure_proxy([row],100,'calls_positive_puts_negative')
    gamma = black76(100,100,.2,.2,.05,'CALL')['gamma_forward']
    assert result['dealer_gex_proxy']==pytest.approx(gamma*10*25*100**2*.01)
    assert result['zero_gamma_flip'] is None
    inverse = gamma_exposure_proxy([{**row,'side':'PUT'}],100,'calls_positive_puts_negative')
    assert inverse['dealer_gex_proxy']==pytest.approx(-result['dealer_gex_proxy'])
    with pytest.raises(ValueError): gamma_exposure_proxy([row],100,'unknown')


def test_flip_at_exact_grid_node_and_identically_zero_chain():
    base = dict(forward=100,tau=.2,iv=.2,open_interest=1,lot_size=1)
    rows = [{**base,'side':'CALL','strike':95,'rate':0},
            {**base,'side':'PUT','strike':105,'rate':.32849674934488937}]
    result = gamma_exposure_proxy(rows,100,'calls_positive_puts_negative')
    assert result['zero_gamma_flip']==pytest.approx(100)
    identical = [{**base,'side':side,'strike':100,'rate':0} for side in ('CALL','PUT')]
    assert gamma_exposure_proxy(identical,100,'calls_positive_puts_negative')['zero_gamma_flip'] is None


def test_import_surface_and_gex_capture_is_explicitly_unverified(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    observed = datetime.now(UTC)
    expiry = observed+timedelta(days=30)
    raw = dict(context=OptionsContext().model_dump(),provenance='Declared pricing scenario',licence='Personal use',observed_at=observed,
        surface_spot=100,gex_sign_assumption='calls_positive_puts_negative',surface_rows=[
            dict(contract_id='call',side='CALL',strike=100,expiry_at=expiry,forward=101,rate=.05,iv=.2,open_interest=50,lot_size=25),
            dict(contract_id='put',side='PUT',strike=100,expiry_at=expiry,forward=101,rate=.05,iv=.2,open_interest=30,lot_size=25)])
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),
            ['get_vol_surface_and_greeks','get_nse_oi_microstructure'],budget=TurnBudget(),historical_input=raw)
        evidence = captured.for_role('options_trading_analysis')
        surface = evidence['get_vol_surface_and_greeks']
        assert surface.metrics['atm_iv']==.2 and len(surface.metrics['rows'])==2
        assert surface.coverage['input_provenance']=='user_declared_unverified'
        assert not surface.candidate_proposals
        assert evidence['get_nse_oi_microstructure'].metrics['dealer_gex_proxy'] is not None
    asyncio.run(run())


def test_dated_iv_history_and_realized_volatility_reach_surface(tmp_path):
    from app.terminal.analytics_inputs import HistoricalAnalyticsInput,AnalyticsInputStore
    from app.terminal.analytics_engine import calculate_evidence
    from pydantic import ValidationError
    _,_,_,store = sources(tmp_path)
    now = datetime.now(UTC)
    raw = dict(context=OptionsContext().model_dump(),provenance='Declared constant-tenor ATM daily IV and RV',licence='Personal',observed_at=now,
        surface_rows=[dict(contract_id='call',side='CALL',strike=100,expiry_at=now+timedelta(days=30),forward=100,rate=.05,iv=.2,open_interest=1,lot_size=25)],
        iv_history_dates=[now-timedelta(days=252-i) for i in range(252)],iv_history=[.1+i*.001 for i in range(252)],
        iv_history_basis='constant_tenor_atm_source_declared',realized_volatility=.15,realized_volatility_basis='annualized_daily_log_returns_source_declared')
    value = HistoricalAnalyticsInput.model_validate(raw)
    records=AnalyticsInputStore(store)
    saved=records.save(7,value)
    inputs,ref,value=records.load(7,saved['dataset_id'],OptionsContext())
    metrics=calculate_evidence('get_vol_surface_and_greeks',inputs,source_refs=(ref,),observed_at=now).metrics
    assert metrics['iv_rank_252d']==pytest.approx((.2-.1)/.251*100)
    assert metrics['iv_rv_spread']==pytest.approx(.05)
    assert metrics['iv_percentile_252d'] is not None
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate({**raw,'iv_history_dates':[now]*252})


def test_declared_cash_future_basis_is_bound_and_available_without_chain(tmp_path):
    from app.terminal.analytics_inputs import HistoricalAnalyticsInput,AnalyticsInputStore
    from app.terminal.analytics_engine import calculate_evidence
    from pydantic import ValidationError
    _,_,_,store=sources(tmp_path)
    now=datetime.now(UTC)
    basis=dict(underlying='NIFTY',future_contract_id='declared-future',expiry_at=now+timedelta(days=30),
        spot=100,future_price=101,spot_observed_at=now,future_observed_at=now,source='Declared synchronized quotes')
    raw=dict(context=OptionsContext().model_dump(),provenance='Declared basis scenario',licence='Personal',observed_at=now,cash_future_basis=basis)
    records=AnalyticsInputStore(store)
    saved=records.save(7,raw)
    inputs,ref,_=records.load(7,saved['dataset_id'],OptionsContext())
    item=calculate_evidence('get_nse_oi_microstructure',inputs,source_refs=(ref,),observed_at=now)
    assert item.status=='PARTIAL'
    assert item.metrics['cash_future_basis']['basis_inr']==1
    assert item.metrics['cash_future_basis']['basis_fraction']==pytest.approx(.01)
    assert 'chain_rows' in item.unavailable_reasons
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate({**raw,'cash_future_basis':{**basis,'future_observed_at':now-timedelta(seconds=11)}})
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate({**raw,'cash_future_basis':{**basis,'underlying':'OTHER'}})
