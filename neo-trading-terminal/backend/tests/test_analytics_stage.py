from datetime import UTC,datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.terminal.analytics_contracts import AnalyticsEvidence


def test_interpretation_cannot_invent_numeric_claims():
    from app.terminal.analytics_stage import SpecialistNarrative
    with pytest.raises(ValidationError):
        SpecialistNarrative(interpretation='The margin is 100 rupees.',claims=[])


def test_claims_resolve_only_current_role_evidence_and_scalar_fields():
    from app.terminal.analytics_stage import SpecialistNarrative,render_narrative
    e = AnalyticsEvidence(calculation_version='oi.1',observed_at=None,retrieved_at=datetime.now(UTC),status='PARTIAL',metrics={'pcr_oi':2,'rows':[]})
    narrative = SpecialistNarrative(interpretation='Coverage is limited.',claims=[{'evidence_id':e.evidence_id,'path':['pcr_oi']}])
    rendered = render_narrative(narrative,{'get_nse_oi_microstructure':e})
    assert rendered['claims'][0]['value']==2
    assert rendered['claims'][0]['evidence_id']==str(e.evidence_id)
    for bad in ({'evidence_id':uuid4(),'path':['pcr_oi']},{'evidence_id':e.evidence_id,'path':['rows']}):
        with pytest.raises(ValueError):
            render_narrative(SpecialistNarrative(interpretation='Coverage is limited.',claims=[bad]),{'get_nse_oi_microstructure':e})


def test_stage_prefetch_is_counted_and_third_section_remains_pending():
    import asyncio
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.terminal.analytics_capture import CapturedAnalytics
    from app.terminal.analytics_runtime import TurnBudget
    from app.terminal.analytics_stage import run_specialist_stage
    from app.terminal.options_snapshot import OptionsContext
    names = ['get_nse_oi_microstructure','get_technical_regime_snapshot','get_vol_surface_and_greeks']
    evidence = {name:AnalyticsEvidence(calculation_version='test.1',observed_at=None,retrieved_at=datetime.now(UTC),status='PARTIAL',metrics={'metric':2}) for name in names}
    captured = CapturedAnalytics(7,'session',OptionsContext().model_dump_json(),tuple((name,item.model_dump_json()) for name,item in evidence.items()))
    budget = TurnBudget()
    class Runtime:
        async def _validate_analytics_discovery(self,capability):
            return None
        @asynccontextmanager
        async def connection(self,user,context,run,**kwargs):
            async def read(name):
                kwargs['analytics_budget'].consume('options_trading_analysis')
                return kwargs['analytics_evidence'][name].model_dump(mode='json')
            yield SimpleNamespace(_snapshot=read,capability=object())
    model = SimpleNamespace(aclose=AsyncMock())
    agent = SimpleNamespace(model=model,arun=AsyncMock(return_value=SimpleNamespace(content={'interpretation':'Coverage is limited.','claims':[]})))
    async def scenario():
        result = await run_specialist_stage(SimpleNamespace(),Runtime(),captured,7,'options_trading_analysis','Explain this.',names,budget,
            agent_factory=lambda config,role:agent)
        assert result['pending_tools']==names[2:]
        assert budget.calls['options_trading_analysis']==2
        assert agent.arun.await_count==1
        assert model.aclose.await_count==1
        assert 'session' not in agent.arun.call_args.args[0]
    asyncio.run(scenario())


def test_capture_to_real_mcp_to_specialist_claim(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.terminal.analytics_capture import AnalyticsCaptureService
    from app.terminal.analytics_runtime import TurnBudget
    from app.terminal.analytics_stage import run_specialist_stage
    from app.terminal.options_mcp import OptionsMCP
    from app.terminal.options_snapshot import OptionsContext
    from test_analytics_capture import sources
    async def scenario():
        market,portfolio,snapshots,store = sources(tmp_path)
        captured = await AnalyticsCaptureService(market,store,snapshots,portfolio).capture(7,OptionsContext(),['get_nse_oi_microstructure'],budget=TurnBudget())
        identity = captured.for_role('options_trading_analysis')['get_nse_oi_microstructure'].evidence_id
        agent = SimpleNamespace(model=SimpleNamespace(aclose=AsyncMock()),arun=AsyncMock(return_value=SimpleNamespace(content={
            'interpretation':'This describes returned strikes only.','claims':[{'evidence_id':str(identity),'path':['pcr_oi']}]})))
        runtime = OptionsMCP(snapshots,port=0,portfolio_service=portfolio)
        budget = TurnBudget()
        async with runtime.lifespan():
            assert runtime.ready
            result = await run_specialist_stage(SimpleNamespace(),runtime,captured,7,'options_trading_analysis','Explain the chain.',
                ['get_nse_oi_microstructure'],budget,agent_factory=lambda config,role:agent)
        assert result['claims'][0]['value']==2
        assert result['status']=='completed'
        assert budget.calls['options_trading_analysis']==1
        assert not runtime.capabilities
        assert snapshots.fetch.call_count==1
    asyncio.run(scenario())


def test_specialists_have_fresh_models_and_no_unbudgeted_tools(tmp_path):
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.terminal.analytics_stage import build_analytics_specialist,SpecialistNarrative
    config = Settings(_env_file=None,data_dir=tmp_path,options_agent_provider='openai',openai_api_key=SecretStr('fixture-key'))
    first = build_analytics_specialist(config,'options_trading_analysis')
    second = build_analytics_specialist(config,'portfolio_analysis')
    assert first.model is not second.model
    assert not first.tools and not second.tools
    assert first.output_schema is SpecialistNarrative
    assert first.model.requests_remaining==1
    assert first.model.key_rotator is None
