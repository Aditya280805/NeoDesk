"""Offline real loopback protocol coverage for portfolio capability boundaries."""
import asyncio
import json
import threading
import time
from datetime import UTC, datetime
from unittest.mock import Mock
import httpx
import pytest
from app.terminal.options_mcp import OptionsMCP, Capability
from app.terminal.options_snapshot import OptionsContext
from app.terminal.portfolio_contracts import PortfolioSnapshot
from app.terminal.portfolio_risk_contracts import RiskPolicy


def service():
    now = datetime.now(UTC)
    collector = Mock()
    collector.assert_generation = Mock()
    collector.fetch.return_value = PortfolioSnapshot(retrieval_started_at=now, retrieval_finished_at=now, source_observed_at=now)
    return collector


def test_portfolio_tool_reuses_immutable_snapshot_and_budget():
    async def scenario():
        collector = service()
        runtime = OptionsMCP(Mock(), port=0, portfolio_service=collector)
        async with runtime.lifespan():
            async with runtime.connection(42, None, 'p', scope='portfolio',risk_policy=RiskPolicy(revision=0), session_generation='g') as conn:
                discovery_names = [t.name for t in (await conn.tools.session.list_tools())]
                assert discovery_names == ['get_portfolio_snapshot']
                first = await conn.portfolio_snapshot()
                changed = dict(first); changed['summary']['forged'] = '999'
                first['risk_report']['limitations'].append('forged-risk')
                second = await conn.portfolio_snapshot()
                assert 'forged-risk' not in second['risk_report']['limitations']
                first['risk_report']['limitations'].pop()
                third = await conn.portfolio_snapshot()
                first['summary'].pop('forged')
                assert first == second == third
                assert first['risk_report']['policy_revision']==0
                assert first['risk_report']['evidence_id']==first['evidence_id']
                assert first['risk_report']['report_id']==second['risk_report']['report_id']
                assert json.dumps(first) == json.dumps(second) == json.dumps(third)
                assert collector.fetch.call_count == 1
                assert collector.fetch.call_args.args == (42,)
                assert collector.fetch.call_args.kwargs['expected_generation'] == 'g'
                with pytest.raises(Exception): await conn.portfolio_snapshot()
                forbidden = await conn.tools.session.call_tool('get_option_snapshot', {}, raise_on_error=False)
                assert forbidden.is_error
            async with runtime.connection(43, OptionsContext(), 'c') as conn:
                assert [t.name for t in (await conn.tools.session.list_tools())] == ['get_option_snapshot']
                assert (await conn.tools.session.call_tool('get_portfolio_snapshot', {}, raise_on_error=False)).is_error
        assert collector.fetch.call_count == 1
    asyncio.run(scenario())


def test_portfolio_rejections_never_collect():
    async def scenario():
        collector = service()
        runtime = OptionsMCP(Mock(), port=0, portfolio_service=collector)
        async with runtime.lifespan():
            async with runtime.connection(7, None, 'p', scope='portfolio',risk_policy=RiskPolicy(revision=0), session_generation='g') as conn:
                assert (await conn.tools.session.call_tool('get_portfolio_snapshot', {'user_id':9}, raise_on_error=False)).is_error
                collector.assert_generation.side_effect = ValueError('PRIVATE provider message')
                assert (await conn.tools.session.call_tool('get_portfolio_snapshot', {}, raise_on_error=False)).is_error
                collector.assert_generation.side_effect = None
                runtime.capabilities[conn.token].deadline_monotonic=0
                assert (await conn.tools.session.call_tool('get_portfolio_snapshot', {}, raise_on_error=False)).is_error
                async with httpx.AsyncClient() as http:
                    for headers in ({}, {'Authorization':'Bearer bad'}, {'Authorization':'Bearer '+conn.token,'Origin':'https://browser.example'}):
                        assert (await http.post(runtime.url,headers=headers,json={})).status_code == 401
                    runtime.capabilities[conn.token].expires=0
                    assert (await http.post(runtime.url,headers={'Authorization':'Bearer '+conn.token},json={})).status_code == 401
                token=conn.token
            async with httpx.AsyncClient() as http:
                assert (await http.post(runtime.url,headers={'Authorization':'Bearer '+token},json={})).status_code == 401
        collector.fetch.assert_not_called()
    asyncio.run(scenario())


def test_cancelled_portfolio_read_retains_pending_capacity():
    async def scenario():
        collector=service(); entered=threading.Event(); release=threading.Event()
        original=collector.fetch.return_value
        def fetch(*args, **kwargs):
            entered.set(); release.wait(3); return original
        collector.fetch.side_effect=fetch
        runtime=OptionsMCP(Mock(),portfolio_service=collector)
        def cap(uid=7):
            return Capability(uid,None,'p',time.monotonic()+65,scope='portfolio',risk_policy=RiskPolicy(revision=0),session_generation='g')
        task=asyncio.create_task(runtime._read(cap()))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set(): await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert 7 in runtime.pending
            with pytest.raises(ValueError,match='already running'): await runtime._read(cap())
            # Both scopes share the same global worker capacity.
            for uid in (8,9,10): runtime.pending[uid]=asyncio.get_running_loop().create_future()
            with pytest.raises(ValueError,match='capacity'): await runtime._read(cap(11))
        finally:
            for uid in (8,9,10): runtime.pending.pop(uid,None)
            release.set(); await asyncio.gather(*runtime.pending.values(),return_exceptions=True)
        expired=cap(); expired.deadline_monotonic=0
        with pytest.raises(ValueError,match='deadline'): await runtime._read(expired)
        assert collector.fetch.call_count==1
    asyncio.run(scenario())

def test_portfolio_cached_reads_recheck_generation_and_users_are_isolated():
    async def scenario():
        collector=service(); runtime=OptionsMCP(Mock(),port=0,portfolio_service=collector)
        async with runtime.lifespan():
            async with runtime.connection(7,None,'a',scope='portfolio',risk_policy=RiskPolicy(revision=0),session_generation='g7') as a:
                await a.portfolio_snapshot()
                collector.assert_generation.side_effect=ValueError('SECRET')
                with pytest.raises(Exception): await a.portfolio_snapshot()
                collector.assert_generation.side_effect=None
            async with runtime.connection(8,None,'b',scope='portfolio',risk_policy=RiskPolicy(revision=0),session_generation='g8') as b:
                await b.portfolio_snapshot()
        assert [c.args for c in collector.fetch.call_args_list]==[(7,),(8,)]
        assert [c.kwargs['expected_generation'] for c in collector.fetch.call_args_list]==['g7','g8']
    asyncio.run(scenario())


def test_cancelled_portfolio_queued_section_does_not_collect_after_deadline(tmp_path, monkeypatch):
    from app.core.config import Settings
    from app.terminal.server import create_app
    from app.terminal.portfolio_service import PortfolioSnapshotService
    async def scenario():
        app=create_app(Settings(_env_file=None,data_dir=tmp_path,environment='test',app_password=None,market_data_source='sample',kotak_consumer_key=None))
        market=app.state.market
        market.get_session(7).broker=Mock(is_authenticated=True)
        broker_call=Mock(return_value={'data':[]})
        monkeypatch.setattr(market,'call',broker_call)
        collector=PortfolioSnapshotService(market,app.state.store)
        fetching=threading.Event();original_fetch=collector.fetch
        def fetch(*args,**kwargs):
            fetching.set();return original_fetch(*args,**kwargs)
        monkeypatch.setattr(collector,'fetch',fetch)
        runtime=OptionsMCP(Mock(),portfolio_service=collector)
        generation=market.session_generation(7)
        capability=Capability(7,None,'p',time.monotonic()+65,scope='portfolio',risk_policy=RiskPolicy(revision=0),session_generation=generation,deadline_monotonic=time.monotonic()+.15)
        # Queue the first section behind another synchronous broker operation.
        market.call_lock.acquire()
        task=asyncio.create_task(runtime._read(capability))
        try:
            async with asyncio.timeout(2):
                while not fetching.is_set(): await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert 7 in runtime.pending
            await asyncio.gather(*runtime.pending.values(),return_exceptions=True)
        finally:
            market.call_lock.release()
        assert not runtime.pending
        broker_call.assert_not_called()
    asyncio.run(scenario())

@pytest.mark.parametrize('validation_stage', ['before_fetch', 'cached', 'publication'])
def test_portfolio_generation_validation_cannot_outlive_deadline(monkeypatch, validation_stage):
    async def scenario():
        from app.terminal import options_mcp
        collector = service()
        runtime = OptionsMCP(Mock(), portfolio_service=collector)
        capability = Capability(7, None, 'p', time.monotonic()+65,
            scope='portfolio',risk_policy=RiskPolicy(revision=0), session_generation='g', deadline_monotonic=time.monotonic()+60)
        if validation_stage == 'cached':
            await runtime._read(capability)
        # A local clock object avoids changing asyncio's clock. The generation
        # worker advances it deterministically instead of relying on sleeps.
        clock = Mock()
        clock.monotonic.return_value = 10.
        capability.expires = 100.
        capability.deadline_monotonic = 20.
        monkeypatch.setattr(options_mcp, 'time', clock)
        validations = [0]
        def validate(*args, **kwargs):
            validations[0] += 1
            if validation_stage != 'publication' or validations[0] == 2:
                clock.monotonic.return_value = 21.
        collector.assert_generation.side_effect = validate
        with pytest.raises(ValueError, match='deadline'):
            await runtime._read(capability)
        if validation_stage == 'before_fetch':
            collector.fetch.assert_not_called()
        elif validation_stage == 'publication':
            assert capability.snapshot_json is None
        assert not runtime.pending
    asyncio.run(scenario())


def test_final_review_force_capability_is_server_bound_and_immutable():
    async def scenario():
        collector=service();runtime=OptionsMCP(Mock(),port=0,portfolio_service=collector)
        async with runtime.lifespan():
            async with runtime.connection(7,None,'refresh',scope='portfolio',risk_policy=RiskPolicy(revision=0),session_generation='g',force_refresh=True) as conn:
                first=await conn.portfolio_snapshot()
                assert await conn.portfolio_snapshot()==first
                assert collector.fetch.call_count==1 and collector.fetch.call_args.kwargs['force'] is True
                assert (await conn.tools.session.call_tool('get_portfolio_snapshot',{'force':True},raise_on_error=False)).is_error
            async with runtime.connection(7,None,'chat',scope='portfolio',risk_policy=RiskPolicy(revision=0),session_generation='g') as conn:
                await conn.portfolio_snapshot()
                assert collector.fetch.call_args.kwargs['force'] is False
    asyncio.run(scenario())


def test_final_review_cancelled_generation_validation_retains_pending():
    async def scenario():
        collector=service();entered=threading.Event();release=threading.Event()
        def validate(*args,**kwargs):
            entered.set();release.wait(3)
        collector.assert_generation.side_effect=validate
        runtime=OptionsMCP(Mock(),portfolio_service=collector)
        cap=Capability(7,None,'validation',time.monotonic()+65,scope='portfolio',risk_policy=RiskPolicy(revision=0),session_generation='g')
        task=asyncio.create_task(runtime._read(cap))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set(): await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert 7 in runtime.pending
            with pytest.raises(ValueError,match='already running'): await runtime._read(cap)
            collector.fetch.assert_not_called()
        finally:
            release.set();await asyncio.gather(*runtime.pending.values(),return_exceptions=True)
        assert not runtime.pending
    asyncio.run(scenario())
