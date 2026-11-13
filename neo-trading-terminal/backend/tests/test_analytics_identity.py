import asyncio
from datetime import UTC,datetime,timedelta
from unittest.mock import Mock

import pytest

from app.terminal.market import parse_master
from app.terminal.options_snapshot import OptionsContext,normalize_snapshot
from app.terminal.analytics_capture import AnalyticsCaptureService
from app.terminal.analytics_runtime import TurnBudget
from test_analytics_capture import sources


def setup(tmp_path):
    market,portfolio,snapshots,store = sources(tmp_path)
    expiry = (datetime.now(UTC)+timedelta(days=30)).date().isoformat()
    context = OptionsContext(expiry=expiry)
    def leg(token,strike):
        return dict(instrument=dict(neoSymbol=f'nse_fo|{token}',symbol=f'opaque-{token}',optionType='CE',strikePrice=strike),
            quote=dict(ltp=2),openInterest=dict(current=10))
    snapshots.fetch.return_value = normalize_snapshot(dict(common_data=dict(unlSymbol='NIFTY',exSeg='nse_fo',expiryDt=expiry,mktLot='25'),
        call=[leg('1',100),leg('2',110)],put=[]),context)
    rows = parse_master('pSymbol,pTrdSymbol,pSymbolName,pExchSeg,pInstType,pOptionType,lLotSize,lExpiryDate,dStrikePrice\n'
        f'1,opaque-1,NIFTY,nse_fo,OPTIDX,CE,25,{expiry},10000\n2,opaque-2,NIFTY,nse_fo,OPTIDX,CE,25,{expiry},11000\n','nse_fo')
    catalogue = Mock()
    catalogue.search.return_value={'items':rows}
    market.call = Mock(return_value=[dict(exchange='nse_fo',exchange_token=token,ltp='2',depth=dict(
        buy=[dict(price=bid,quantity='25')],sell=[dict(price=ask,quantity='25')])) for token,bid,ask in (('1','2','2.1'),('2','1','1.1'))])
    return market,portfolio,snapshots,store,catalogue,context


def test_documented_identity_candidates_are_prebound_without_third_call(tmp_path):
    market,portfolio,snapshots,store,catalogue,context = setup(tmp_path)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue,advisory_enabled=True).capture(7,context,
            ['get_nse_oi_microstructure'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_nse_oi_microstructure']
        assert len(item.candidate_proposals)==1
        proposal = item.candidate_proposals[0]
        assert proposal.evidence_id==item.evidence_id
        assert proposal.legs[0].underlying_key=='nse_fo:OPTIDX:NIFTY'
        assert proposal.legs[0].contract_id=='nse_fo|1'
        assert snapshots.fetch.call_count==1 and market.call.call_count==1
        from dataclasses import replace
        from app.terminal.analytics_contracts import AnalyticsEvidence
        from app.terminal.analytics_handoff import project_proposal
        placeholder = AnalyticsEvidence(calculation_version='cost.1',observed_at=None,retrieved_at=datetime.now(UTC),status='UNAVAILABLE',metrics={})
        captured = replace(captured,evidence_json=(*captured.evidence_json,('compute_indian_statutory_costs_and_payoff',placeholder.model_dump_json())))
        downstream,_ = project_proposal(captured,proposal,'portfolio_analysis')
        handoff = downstream.for_role('portfolio_analysis')['compute_indian_statutory_costs_and_payoff'].metrics['proposal_handoff']
        assert handoff['gross_terminal_payoff']['gross_max_loss_paise']==2750
        assert handoff['gross_terminal_payoff']['net_max_profit_paise'] is None
        assert handoff['entry_fee_estimate']['total_paise'] is None
        assert handoff['entry_fee_estimate']['transactions'][1]['charges']['stt_paise']>0
        assert market.call.call_count==1
    asyncio.run(run())


def test_advisory_disabled_keeps_depth_without_candidates(tmp_path):
    market,portfolio,snapshots,store,catalogue,context=setup(tmp_path)
    async def run():
        captured=await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(7,context,
            ['get_nse_oi_microstructure'],budget=TurnBudget())
        item=captured.for_role('options_trading_analysis')['get_nse_oi_microstructure']
        assert item.metrics['broker_quote_depth']['quotes']
        assert not item.candidate_proposals
    asyncio.run(run())


def test_explicit_master_contradiction_rejects_before_quotes(tmp_path):
    market,portfolio,snapshots,store,catalogue,context = setup(tmp_path)
    catalogue.search.return_value['items'][0]['identity_source_fields']['pSymbolName']='OTHER'
    with pytest.raises(ValueError):
        asyncio.run(AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue).capture(7,context,
            ['get_nse_oi_microstructure'],budget=TurnBudget()))
    market.call.assert_not_called()


def test_non_iso_provider_expiry_is_canonicalized_for_candidates(tmp_path):
    market,portfolio,snapshots,store,catalogue,context = setup(tmp_path)
    old = snapshots.fetch.return_value
    provider_expiry = datetime.fromisoformat(context.expiry).strftime('%d%b%Y').upper()
    snapshots.fetch.return_value = normalize_snapshot(dict(common_data=dict(unlSymbol='NIFTY',exSeg='nse_fo',expiryDt=provider_expiry,mktLot='25'),
        call=[dict(instrument=dict(neoSymbol=row['contract_id'],symbol=row['symbol'],optionType='CE',strikePrice=row['strike']),
            quote=dict(ltp=2,prevClose=1),openInterest=dict(current=10,previous=5)) for row in old['rows']],put=[]),context)
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue,advisory_enabled=True).capture(7,context,['get_nse_oi_microstructure'],budget=TurnBudget())
        item = captured.for_role('options_trading_analysis')['get_nse_oi_microstructure']
        assert str(item.candidate_proposals[0].legs[0].expiry)==context.expiry
        assert item.metrics['rows'][0]['buildup']=='LONG_BUILDUP'
    asyncio.run(run())


def test_combined_supplied_position_stress_uses_bound_import_without_extra_fetch(tmp_path):
    from app.terminal.analytics_inputs import AnalyticsInputStore
    from app.terminal.analytics_handoff import project_proposal
    market,portfolio,snapshots,store,catalogue,context = setup(tmp_path)
    observed = datetime.now(UTC)
    expiry_at = datetime.fromisoformat(context.expiry+'T15:30:00+05:30')
    raw = dict(context=context.model_dump(),observed_at=observed,provenance='Declared aligned valuation inputs',licence='Personal',
        risk_positions=[dict(contract_id='cash',underlying='NIFTY',kind='equity',quantity=10,spot=100)],surface_spot=100,
        surface_rows=[dict(contract_id=f'nse_fo|{token}',side='CALL',strike=strike,expiry_at=expiry_at,forward=101,rate=.05,iv=.2,open_interest=10,lot_size=25) for token,strike in (('1',100),('2',110))])
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue,advisory_enabled=True).capture(7,context,
            ['get_nse_oi_microstructure','run_spot_vix_cvar_stress_matrix'],budget=TurnBudget(),historical_input=raw)
        item = captured.for_role('options_trading_analysis')['get_nse_oi_microstructure']
        proposal = item.candidate_proposals[0]
        inputs,_,declared = AnalyticsInputStore(store).load(7,captured.input_dataset_id,context)
        projected,_ = project_proposal(captured,proposal,'portfolio_risk',quant_inputs=inputs,valuation_time=declared.observed_at)
        handoff = projected.for_role('portfolio_risk')['run_spot_vix_cvar_stress_matrix'].metrics['proposal_handoff']
        result = handoff['combined_supplied_position_stress']
        assert result['position_count']==3 and len(result['cells'])==28
        assert result['complete_account_coverage'] is False and result['risk_verdict']=='CANNOT_ASSESS'
        stale,_ = project_proposal(captured,proposal,'portfolio_risk',quant_inputs=inputs,valuation_time=declared.observed_at-timedelta(minutes=1))
        stale_handoff = stale.for_role('portfolio_risk')['run_spot_vix_cvar_stress_matrix'].metrics['proposal_handoff']
        assert stale_handoff['combined_supplied_position_stress'] is None
        assert 'same_capture_window' in stale_handoff['combined_stress_unavailable_reason']
        assert market.call.call_count==1
    asyncio.run(run())


def test_conditional_cost_scenario_requires_exact_quote_and_contract_binding(tmp_path):
    from app.terminal.analytics_inputs import AnalyticsInputStore
    from app.terminal.analytics_handoff import project_proposal
    market,portfolio,snapshots,store,catalogue,context = setup(tmp_path)
    observed = datetime.now(UTC)
    raw = dict(context=context.model_dump(),observed_at=observed,provenance='Explicit fixed cost scenario',licence='Personal',proposal_cost_scenarios=[dict(
        template='bull_call_spread',buy_contract_id='nse_fo|1',sell_contract_id='nse_fo|2',expiry=context.expiry,quantity=25,valued_at=observed,
        buy_bid='2',buy_ask='2.1',sell_bid='1',sell_ask='1.1',roundtrip_cost_paise=100,source='Declared fixed roundtrip scenario')])
    async def run():
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio,catalogue=catalogue,advisory_enabled=True).capture(7,context,
            ['get_nse_oi_microstructure','compute_indian_statutory_costs_and_payoff'],budget=TurnBudget(),historical_input=raw)
        proposal = captured.for_role('options_trading_analysis')['get_nse_oi_microstructure'].candidate_proposals[0]
        inputs,_,declared = AnalyticsInputStore(store).load(7,captured.input_dataset_id,context)
        downstream,_ = project_proposal(captured,proposal,'portfolio_analysis',quant_inputs=inputs,valuation_time=declared.observed_at)
        handoff = downstream.for_role('portfolio_analysis')['compute_indian_statutory_costs_and_payoff'].metrics['proposal_handoff']
        assert handoff['gross_terminal_payoff']['net_max_loss_paise']==2850
        assert handoff['cost_scenario']['roundtrip_cost_paise']==100
        inputs['proposal_cost_scenarios'][0]['buy_ask']=3
        other,_ = project_proposal(captured,proposal,'portfolio_analysis',quant_inputs=inputs,valuation_time=declared.observed_at)
        assert other.for_role('portfolio_analysis')['compute_indian_statutory_costs_and_payoff'].metrics['proposal_handoff']['cost_scenario'] is None
        assert market.call.call_count==1
    asyncio.run(run())
