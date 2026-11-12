import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.terminal.analytics_contracts import RoutingDecision
from app.terminal.options_snapshot import OptionsContext
from test_analytics_capture import sources


def test_coordinator_resumes_only_pending_tools_and_replays(tmp_path):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    from app.terminal.analytics_coordinator import AnalyticsCoordinator
    from app.terminal.analytics_continuation import Continuations
    market, portfolio, snapshots, store = sources(tmp_path)
    capture = AnalyticsCaptureService(market, store, snapshots, portfolio)
    classifier = AsyncMock(return_value=RoutingDecision(mode='SINGLE_OPTIONS', delegated_agents=('options_trading_analysis',)))
    calls = []
    async def stage(config, mcp, captured, user, role, question, names, budget, **kwargs):
        selected = list(names)[:2]
        calls.extend(selected)
        return dict(role=role, status='partial' if len(names)>2 else 'completed', pending_tools=list(names)[2:], evidence={}, interpretation='Limited coverage.', claims=[])
    coordinator = AnalyticsCoordinator(SimpleNamespace(), capture, None, Continuations(store), classifier=classifier, stage=stage)
    async def run():
        first = await coordinator.start(7, 'Explain options.', OptionsContext(), policy_revision=0)
        assert first['status']=='partial'
        key = first['continuation_id']
        second = await coordinator.resume(7, key, 'action-a', 'Explain options.', OptionsContext(), policy_revision=0)
        assert second['status']=='completed'
        assert len(calls)==3 and len(set(calls))==3
        replay = await coordinator.resume(7, key, 'action-a', 'Explain options.', OptionsContext(), policy_revision=0)
        assert replay==second and len(calls)==3
        assert classifier.await_count==1 and snapshots.fetch.call_count==1
        assert 'session-7' not in str(first)+str(second)
        with pytest.raises(ValueError):
            await coordinator.resume(7, key, 'changed', 'Different question', OptionsContext(), policy_revision=0)
        with pytest.raises(ValueError):
            await coordinator.resume(8, key, 'other-owner', 'Explain options.', OptionsContext(), policy_revision=0)
        with pytest.raises(ValueError):
            await coordinator.resume(7, key, 'changed-policy', 'Explain options.', OptionsContext(), policy_revision=1)
        portfolio.assert_generation.side_effect = ValueError('Expired broker authentication')
        with pytest.raises(ValueError):
            await coordinator.resume(7, key, 'action-a', 'Explain options.', OptionsContext(), policy_revision=0)
        assert len(calls)==3
    asyncio.run(run())


def test_invalid_router_sections_rejected_before_capture(tmp_path):
    from app.terminal.analytics_coordinator import AnalyticsCoordinator
    from app.terminal.analytics_runtime import BoundedWork
    classifier = AsyncMock(return_value=RoutingDecision(mode='SINGLE_OPTIONS', delegated_agents=('options_trading_analysis',), requested_sections=('check_sebi_and_mwpl_compliance',)))
    capture = SimpleNamespace(capture=AsyncMock(), market=SimpleNamespace(session_generation=lambda user:'session'), work=BoundedWork())
    coordinator = AnalyticsCoordinator(SimpleNamespace(), capture, None, None, classifier=classifier)
    with pytest.raises(ValueError):
        asyncio.run(coordinator.start(7, 'Explain', OptionsContext(), policy_revision=0))
    capture.capture.assert_not_awaited()
    classifier.return_value = RoutingDecision(mode='COMPOSITE_PIPELINE', delegated_agents=('options_trading_analysis','portfolio_risk'), requested_sections=('get_nse_oi_microstructure',))
    with pytest.raises(ValueError):
        asyncio.run(coordinator.start(7, 'Explain options and risk', OptionsContext(), policy_revision=0))
    capture.capture.assert_not_awaited()


def test_generation_lookup_does_not_block_event_loop(tmp_path):
    from threading import Event
    from app.terminal.analytics_capture import AnalyticsCaptureService
    from app.terminal.analytics_coordinator import AnalyticsCoordinator
    from app.terminal.analytics_continuation import Continuations
    market, portfolio, snapshots, store = sources(tmp_path)
    entered, release = Event(), Event()
    original = market.session_generation
    def blocking(user):
        entered.set()
        release.wait(2)
        return original(user)
    market.session_generation = blocking
    capture = AnalyticsCaptureService(market, store, snapshots, portfolio)
    classifier = AsyncMock(return_value=RoutingDecision(mode='CLARIFY'))
    coordinator = AnalyticsCoordinator(SimpleNamespace(), capture, None, Continuations(store), classifier=classifier)
    async def run():
        task = asyncio.create_task(coordinator.start(7, 'Hello', OptionsContext(), policy_revision=0))
        try:
            for _ in range(100):
                await asyncio.sleep(.001)
                if entered.is_set():
                    break
            assert entered.is_set() and not task.done()
        finally:
            release.set()
        assert (await task)['status']=='clarify'
    asyncio.run(run())


def test_historical_import_is_bound_to_continuation_and_not_recaptured(tmp_path):
    from app.terminal.analytics_capture import AnalyticsCaptureService
    from app.terminal.analytics_coordinator import AnalyticsCoordinator
    from app.terminal.analytics_continuation import Continuations
    from test_analytics_inputs import declared
    market, portfolio, snapshots, store = sources(tmp_path)
    capture = AnalyticsCaptureService(market,store,snapshots,portfolio)
    raw = declared()
    # Historical observations remain useful as historical evidence, never live claims.
    raw['observed_at'] -= timedelta(days=100)
    raw['bars'] = [{**bar,'time':bar['time']-timedelta(days=100)} for bar in raw['bars']]
    raw['return_dates'] = [t-timedelta(days=100) for t in raw['return_dates']]
    classifier = AsyncMock(return_value=RoutingDecision(mode='SINGLE_OPTIONS',delegated_agents=('options_trading_analysis',)))
    calls = []
    async def stage(config,mcp,captured,user,role,question,names,budget,**kwargs):
        calls.append(names[:2])
        return dict(role=role,status='partial' if len(names)>2 else 'completed',pending_tools=names[2:],evidence={},interpretation='Historical coverage.',claims=[])
    coordinator = AnalyticsCoordinator(SimpleNamespace(),capture,None,Continuations(store),classifier=classifier,stage=stage)
    async def run():
        first = await coordinator.start(7,'Explain',OptionsContext(),policy_revision=0,historical_input=raw)
        altered = {**raw,'provenance':'Changed source'}
        with pytest.raises(ValueError):
            await coordinator.resume(7,first['continuation_id'],'changed','Explain',OptionsContext(),policy_revision=0,historical_input=altered)
        result = await coordinator.resume(7,first['continuation_id'],'correct','Explain',OptionsContext(),policy_revision=0,historical_input=raw)
        assert result['status']=='completed' and len(calls)==2
        assert snapshots.fetch.call_count==1
    asyncio.run(run())
