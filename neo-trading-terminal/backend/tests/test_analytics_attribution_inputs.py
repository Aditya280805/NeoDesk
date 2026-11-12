import asyncio
from datetime import UTC,datetime,timedelta

import pytest

from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources
from app.terminal.analytics_inputs import HistoricalAnalyticsInput
from pydantic import ValidationError


def declared():
    now = datetime.now(UTC)
    dates = [now-timedelta(days=40-i) for i in range(40)]
    return dict(context=OptionsContext().model_dump(),provenance='Adjusted cash history and closed fills',licence='Personal use',observed_at=now,
        asset_price_dates=dates,cash_assets=[
            dict(asset_id='cash-a',kind='cash_equity',sector='Banks',value_paise=10000,adjusted_prices=[100+i*.2+(i%3) for i in range(40)]),
            dict(asset_id='cash-b',kind='cash_etf',sector='ETF',value_paise=30000,adjusted_prices=[120+i*.1+(i%5)*.3 for i in range(40)]),
            dict(asset_id='option',kind='option',sector='Banks',value_paise=50000,adjusted_prices=[10+i for i in range(40)])],
        closed_trades=[dict(trade_id='win',closed_at=dates[-2],net_pnl_paise=300),dict(trade_id='loss',closed_at=dates[-1],net_pnl_paise=-100)],
        trade_history_complete=True,trade_period_start=dates[0],trade_period_end=now)


def test_annualized_regression_alpha_uses_aligned_benchmark_excess_returns():
    from app.terminal.quant_attribution import portfolio_attribution
    benchmark=[.01,-.005,.003,-.002]*10
    returns=[.001+1.5*value for value in benchmark]
    metrics=portfolio_attribution(returns,benchmark=benchmark)
    assert metrics['beta_nifty50']==pytest.approx(1.5)
    assert metrics['alpha_nifty50_annualized']==pytest.approx(.252)
    assert metrics['alpha_niftybank_annualized'] is None


def test_capture_hrp_excludes_derivatives_and_keeps_independent_trade_metrics(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),
            ['get_portfolio_attribution_and_rebalance'],budget=TurnBudget(),historical_input=declared())
        item = captured.for_role('portfolio_analysis')['get_portfolio_attribution_and_rebalance']
        assert set(item.metrics['hrp_weights'])=={'cash-a','cash-b'}
        assert sum(item.metrics['hrp_weights'].values())==pytest.approx(1)
        assert all(value>=0 for value in item.metrics['hrp_weights'].values())
        assert item.metrics['win_rate']==.5 and item.metrics['profit_factor']==3
        assert item.metrics['sector_allocation']['Banks']==.25
        assert item.metrics['cash_asset_hhi']==pytest.approx(.625)
        assert item.metrics['cash_correlation_matrix']['cash-a']['cash-a']==pytest.approx(1)
        assert 'option' not in item.metrics['cash_correlation_matrix']
        assert item.metrics['sharpe'] is None
        assert 'win_rate' not in item.unavailable_reasons
        assert item.coverage['input_provenance']=='user_declared_unverified'
        assert item.metrics['hrp_coverage']['excluded_assets']==['option']
        assert item.metrics['trade_coverage']['period_start'] is not None
        assert item.metrics['trade_coverage']['completeness']=='user_declared_complete'
        snapshots.fetch.assert_not_called()
    asyncio.run(run())


def test_partial_and_zero_variance_inputs_preserve_other_metrics(tmp_path):
    from app.terminal.analytics_inputs import AnalyticsInputStore
    from app.terminal.analytics_engine import calculate_evidence
    _,_,_,store = sources(tmp_path)
    raw = declared()
    raw['trade_history_complete']=False
    for asset in raw['cash_assets'][:2]: asset['adjusted_prices']=[100]*40
    records = AnalyticsInputStore(store)
    saved = records.save(7,raw)
    inputs,reference,value = records.load(7,saved['dataset_id'],OptionsContext())
    result = calculate_evidence('get_portfolio_attribution_and_rebalance',inputs,source_refs=(reference,),observed_at=value.observed_at)
    assert result.metrics['hrp_weights'] is None
    assert result.metrics['hrp_coverage']['reason']=='zero_variance_cash_returns'
    assert result.metrics['win_rate'] is None
    assert result.metrics['profit_factor'] is None
    assert result.metrics['sector_allocation']['Banks']==.25


def test_geometric_constant_returns_do_not_create_rounding_noise_hrp():
    from app.terminal.quant_attribution import declared_attribution
    raw = declared()
    for asset,rate in zip(raw['cash_assets'][:2],(.01,.02)):
        asset['adjusted_prices']=[100*(1+rate)**i for i in range(40)]
    result = declared_attribution(dict(assets=raw['cash_assets'],dates=raw['asset_price_dates'],trades=raw['closed_trades'],trade_history_complete=True))
    assert result['hrp_weights'] is None
    assert result['sector_allocation']['Banks']==.25
    assert result['win_rate']==.5
    from app.terminal.quant_attribution import portfolio_attribution
    ratios = portfolio_attribution([.01]*30,benchmark=[.02]*30)
    assert ratios['sharpe'] is None and ratios['beta_nifty50'] is None


def test_attribution_import_rejects_misalignment_duplicate_and_outside_period():
    raw = declared()
    raw['cash_assets'][0]['adjusted_prices'].pop()
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)


def test_authenticated_attribution_api_handles_no_loss_denominator(tmp_path):
    from fastapi.testclient import TestClient
    from test_analytics_route import application
    raw = declared()
    raw['closed_trades']=raw['closed_trades'][:1]
    payload = HistoricalAnalyticsInput.model_validate(raw).model_dump(mode='json')
    app,_ = application(tmp_path,True)
    with TestClient(app) as client:
        response = client.post('/api/options-agent/analytics/snapshot',headers={'x-test-auth':'yes'},json={
            'role':'portfolio_analysis','tools':['get_portfolio_attribution_and_rebalance'],'historical_input':payload})
        assert response.status_code==200
        item = response.json()['evidence']['get_portfolio_attribution_and_rebalance']
        assert item['metrics']['win_rate']==1
        assert item['metrics']['profit_factor'] is None
        assert item['unavailable_reasons']['profit_factor']=='no_realized_loss_denominator'
        assert set(item['metrics']['hrp_weights'])=={'cash-a','cash-b'}
    raw = declared()
    raw['closed_trades'][1]['trade_id']='win'
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
    raw = declared()
    raw['closed_trades'][1]['closed_at']=raw['trade_period_end']+timedelta(days=1)
    with pytest.raises(ValidationError): HistoricalAnalyticsInput.model_validate(raw)
