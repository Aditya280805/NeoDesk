import asyncio
from datetime import UTC,datetime
from unittest.mock import Mock

from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_snapshot import OptionsContext
from app.terminal.portfolio_contracts import PortfolioSnapshot,PortfolioSection,PortfolioRow
from app.terminal.portfolio_risk_contracts import RiskPolicy
from test_analytics_capture import sources
from app.brokers.base_broker import BrokerError


def test_capture_exposes_derived_account_report_only_to_risk(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    now = datetime.now(UTC)
    private = PortfolioSnapshot(retrieval_started_at=now,retrieval_finished_at=now,source_observed_at=now,
        sections={'holdings':PortfolioSection(state='partial',rows=[PortfolioRow(row_id='private-row',symbol='PRIVATE_ACCOUNT_SYMBOL')])},
        summary={'available':'12345'})
    portfolio.fetch.return_value=private
    policies = Mock(return_value=RiskPolicy(revision=1))
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,risk_policy_reader=policies).capture(7,OptionsContext(),
            ['check_sebi_and_mwpl_compliance','run_spot_vix_cvar_stress_matrix','get_portfolio_attribution_and_rebalance'],budget=TurnBudget())
        risk = captured.for_role('portfolio_risk')
        analysis = captured.for_role('portfolio_analysis')
        for item in risk.values():
            assert item.status=='PARTIAL'
            assert item.metrics['existing_account_risk_report']['summary']=='cannot_assess'
            assert item.coverage['account_risk_basis']=='existing_account_only_not_combined_with_proposal'
            assert 'PRIVATE_ACCOUNT_SYMBOL' not in item.model_dump_json()
            assert '12345' not in item.model_dump_json()
        for item in analysis.values():
            assert 'existing_account_risk_report' not in item.metrics
            assert str(private.evidence_id) not in item.source_refs
        portfolio.fetch.assert_called_once()
    asyncio.run(run())


def test_account_source_failure_preserves_other_captured_evidence(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    portfolio.fetch.side_effect = BrokerError('private provider failure')
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,
            risk_policy_reader=Mock(return_value=RiskPolicy(revision=1))).capture(7,OptionsContext(),
            ['get_nse_oi_microstructure','run_spot_vix_cvar_stress_matrix'],budget=TurnBudget())
        assert captured.for_role('options_trading_analysis')['get_nse_oi_microstructure'].metrics
        item = captured.for_role('portfolio_risk')['run_spot_vix_cvar_stress_matrix']
        assert item.unavailable_reasons['existing_account_risk_report']=='broker_account_source_unavailable'
        assert 'private provider failure' not in item.model_dump_json()
        assert 'existing_account_risk_report' not in item.metrics
    asyncio.run(run())
