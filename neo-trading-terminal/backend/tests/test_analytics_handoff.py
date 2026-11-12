from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.terminal.analytics_contracts import AnalyticsEvidence
from app.terminal.analytics_capture import CapturedAnalytics
from app.terminal.options_snapshot import OptionsContext
from app.terminal.quant_proposals import candidate_proposals


def fixture():
    identity = uuid4()
    contracts = [dict(identity_verified=True,contract_id=str(strike),underlying_key='NIFTY',exchange='nse_fo',currency='INR',
        expiry='2026-12-29',lot_size=25,strike=str(strike),option_type='CALL') for strike in (24000,24100)]
    candidates = candidate_proposals(contracts,identity,datetime.now(UTC))
    option = AnalyticsEvidence(evidence_id=identity,calculation_version='options.1',observed_at=None,retrieved_at=datetime.now(UTC),status='PARTIAL',metrics={},candidate_proposals=candidates)
    risk = AnalyticsEvidence(calculation_version='risk.1',observed_at=None,retrieved_at=datetime.now(UTC),status='PARTIAL',metrics={'baseline':'account only'})
    captured = CapturedAnalytics(7,'generation',OptionsContext().model_dump_json(),(('get_vol_surface_and_greeks',option.model_dump_json()),('check_sebi_and_mwpl_compliance',risk.model_dump_json())))
    return captured,option,candidates[0]


def test_handoff_resolves_only_consumed_original_options_candidates():
    from app.terminal.analytics_handoff import resolve_selection
    captured,item,proposal = fixture()
    result = dict(role='options_trading_analysis',selected_proposal_id=str(proposal.proposal_id),evidence={'get_vol_surface_and_greeks':item.model_dump(mode='json')})
    assert resolve_selection(captured,result)==proposal
    with pytest.raises(ValueError): resolve_selection(captured,{**result,'role':'portfolio_risk'})
    with pytest.raises(ValueError): resolve_selection(captured,{**result,'evidence':{}})
    with pytest.raises(ValueError): resolve_selection(captured,{**result,'selected_proposal_id':str(uuid4())})
    tampered = item.model_dump(mode='json')
    tampered['metrics']={'invented':True}
    with pytest.raises(ValueError): resolve_selection(captured,{**result,'evidence':{'get_vol_surface_and_greeks':tampered}})


def test_projection_keeps_role_isolation_and_does_not_claim_post_trade_risk():
    from app.terminal.analytics_handoff import project_proposal
    captured,item,proposal = fixture()
    projected,new_items = project_proposal(captured,proposal,'portfolio_risk')
    risk = projected.for_role('portfolio_risk')['check_sebi_and_mwpl_compliance']
    assert risk.metrics['proposal_handoff']['proposal']['proposal_id']==str(proposal.proposal_id)
    assert risk.metrics['proposal_handoff']['assessment']=='CANNOT_ASSESS'
    assert risk.evidence_id != captured.for_role('portfolio_risk')['check_sebi_and_mwpl_compliance'].evidence_id
    assert projected.for_role('options_trading_analysis')['get_vol_surface_and_greeks']==item
    assert len(new_items)==1 and not risk.candidate_proposals


def test_coordinator_persists_selection_and_projects_without_extra_tool_call(tmp_path):
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.terminal.analytics_capture import AnalyticsCaptureService
    from app.terminal.analytics_coordinator import AnalyticsCoordinator
    from app.terminal.analytics_continuation import Continuations
    from app.terminal.analytics_contracts import RoutingDecision
    from test_analytics_capture import sources
    market,portfolio,snapshots,store = sources(tmp_path)
    capture = AnalyticsCaptureService(market,store,snapshots,portfolio)
    captured,item,proposal = fixture()
    captured = replace(captured,session_generation=market.session_generation(7))
    extra = item.model_copy(update={'evidence_id':uuid4(),'candidate_proposals':()})
    captured = replace(captured,evidence_json=(*captured.evidence_json,
        ('get_technical_regime_snapshot',extra.model_dump_json()),('get_nse_oi_microstructure',extra.model_dump_json())))
    capture.capture = AsyncMock(return_value=captured)
    classifier = AsyncMock(return_value=RoutingDecision(mode='COMPOSITE_PIPELINE',
        delegated_agents=('options_trading_analysis','portfolio_risk'),
        requested_sections=('get_vol_surface_and_greeks','get_technical_regime_snapshot','get_nse_oi_microstructure','check_sebi_and_mwpl_compliance')))
    observed = []
    async def stage(config,mcp,evidence,user,role,question,names,budget,**kwargs):
        selected,pending = names[:2],names[2:]
        for name in selected: budget.consume(role)
        payload = evidence.for_role(role)
        observed.append((role,budget.calls.copy()))
        if role=='portfolio_risk':
            assert payload['check_sebi_and_mwpl_compliance'].metrics['proposal_handoff']['proposal']['proposal_id']==str(proposal.proposal_id)
        return dict(role=role,status='partial' if pending else 'completed',pending_tools=pending,interpretation='Limited evidence.',claims=[],
            evidence={name:payload[name].model_dump(mode='json') for name in selected},
            selected_proposal_id=str(proposal.proposal_id) if 'get_vol_surface_and_greeks' in selected else None)
    async def run():
        coordinator = AnalyticsCoordinator(SimpleNamespace(),capture,None,Continuations(store),classifier=classifier,stage=stage)
        result = await coordinator.start(7,'Explain this proposal and risk',OptionsContext(),policy_revision=0)
        assert result['selected_proposal']['proposal_id']==str(proposal.proposal_id)
        assert result['status']=='partial'
        result = await coordinator.resume(7,result['continuation_id'],'resume','Explain this proposal and risk',OptionsContext(),policy_revision=0)
        assert result['status']=='completed'
        assert result['selected_proposal']['proposal_id']==str(proposal.proposal_id)
        risk = result['stages'][2]['evidence']['check_sebi_and_mwpl_compliance']
        assert store.read(7,risk['evidence_id'])==risk
        assert observed[-1][1]=={'options_trading_analysis':1,'portfolio_risk':1}
        assert capture.capture.await_count==1
    asyncio.run(run())
