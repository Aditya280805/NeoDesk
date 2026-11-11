"""Specialist evidence isolation and protocol authorization regressions."""
import asyncio
import time
import threading
from unittest.mock import Mock

import pytest

from app.terminal.options_mcp import Capability, OptionsMCP
from app.terminal.portfolio_risk_contracts import RiskPolicy
from test_portfolio_mcp import service


@pytest.mark.parametrize('scope', ['portfolio_analysis', 'risk'])
def test_cancelled_specialist_retains_broker_capacity(scope):
    async def scenario():
        collector = service()
        entered, release = threading.Event(), threading.Event()
        snapshot = collector.fetch.return_value
        def fetch(*args, **kwargs):
            entered.set()
            release.wait(3)
            return snapshot
        collector.fetch.side_effect = fetch
        runtime = OptionsMCP(Mock(), portfolio_service=collector)
        def capability():
            return Capability(42, None, 'cancel', time.monotonic()+65, scope=scope,
                session_generation='g', risk_policy=RiskPolicy(revision=0))
        task = asyncio.create_task(runtime._read(capability()))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert 42 in runtime.pending
            with pytest.raises(ValueError, match='already running'):
                await runtime._read(capability())
        finally:
            release.set()
            await asyncio.gather(*runtime.pending.values(), return_exceptions=True)
        assert not runtime.pending
        assert collector.fetch.call_count == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('scope,tool', [
    ('portfolio_analysis', 'get_portfolio_analysis_snapshot'),
    ('risk', 'get_portfolio_risk_report'),
])
def test_specialist_projection_is_detached_cached_and_scoped(scope, tool):
    async def scenario():
        collector = service()
        runtime = OptionsMCP(Mock(), port=0, portfolio_service=collector)
        async with runtime.lifespan():
            assert runtime.ready
            async with runtime.connection(42, None, 'specialist', scope=scope,
                    risk_policy=RiskPolicy(revision=0), session_generation='g') as conn:
                assert [t.name for t in await conn.tools.session.list_tools()] == [tool]
                first = await conn._snapshot(tool)
                if scope == 'portfolio_analysis':
                    assert 'sections' in first and 'risk_report' not in first
                    first['summary']['forged'] = 'value'
                else:
                    assert set(first) == {'evidence_id', 'risk_report'}
                    assert first['evidence_id'] == first['risk_report']['evidence_id']
                    first['risk_report']['limitations'].append('forged')
                second = await conn._snapshot(tool)
                assert 'forged' not in str(second)
                assert collector.fetch.call_count == 1
                for forbidden in ('get_portfolio_snapshot', 'get_option_snapshot',
                        'get_strategy_report', 'get_scan_report', 'get_alert_report', 'get_backtest_report',
                        'get_portfolio_risk_report' if scope == 'portfolio_analysis' else 'get_portfolio_analysis_snapshot'):
                    assert (await conn.tools.session.call_tool(forbidden, {}, raise_on_error=False)).is_error
                assert (await conn.tools.session.call_tool(tool, {'user_id': 9}, raise_on_error=False)).is_error
                await conn._snapshot(tool)
                with pytest.raises(Exception):
                    await conn._snapshot(tool)
    asyncio.run(scenario())


def test_all_scope_discovery_and_invocation_matrix():
    async def scenario():
        from fastmcp import Client
        from app.terminal.options_snapshot import OptionsContext
        names = {'chain': 'get_option_snapshot', 'portfolio': 'get_portfolio_snapshot',
                 'portfolio_analysis': 'get_portfolio_analysis_snapshot', 'risk': 'get_portfolio_risk_report'}
        names.update({kind: f'get_{kind}_report' for kind in ('strategy', 'scan', 'alert', 'backtest')})
        runtime = OptionsMCP(Mock(), port=0, portfolio_service=service())
        async with runtime.lifespan():
            for scope, allowed in names.items():
                token = 'synthetic-' + scope
                cap = Capability(42, OptionsContext() if scope == 'chain' else None,
                    'matrix', time.monotonic()+65, scope=scope, session_generation='g',
                    risk_policy=RiskPolicy(revision=0))
                runtime.capabilities[token] = cap
                async with Client(runtime.url, auth=token) as client:
                    assert [t.name for t in await client.list_tools()] == [allowed]
                    for tool in names.values():
                        if tool != allowed:
                            assert (await client.call_tool(tool, {}, raise_on_error=False)).is_error
                    assert (await client.call_tool(allowed, {'owner': 999}, raise_on_error=False)).is_error
                    assert cap.calls == 0
                runtime.capabilities.pop(token)
        with pytest.raises(ValueError):
            Capability(42, None, 'router', time.monotonic()+60, scope='master_router')
    asyncio.run(scenario())


@pytest.mark.parametrize('scope', ['portfolio_analysis', 'risk'])
def test_specialist_auth_lifetime(scope):
    async def scenario():
        import httpx
        runtime = OptionsMCP(Mock(), port=0, portfolio_service=service())
        async with runtime.lifespan():
            async with runtime.connection(42, None, 'auth', scope=scope,
                    risk_policy=RiskPolicy(revision=0), session_generation='g') as conn:
                token = conn.token
                async with httpx.AsyncClient() as client:
                    for headers in ({}, {'Authorization': 'Bearer bad'},
                            {'Authorization': 'Bearer '+token, 'Origin': 'https://example.com'}):
                        assert (await client.post(runtime.url, headers=headers, json={})).status_code == 401
                    runtime.capabilities[token].expires = 0
                    assert (await client.post(runtime.url, headers={'Authorization': 'Bearer '+token}, json={})).status_code == 401
            async with httpx.AsyncClient() as client:
                assert (await client.post(runtime.url, headers={'Authorization': 'Bearer '+token}, json={})).status_code == 401
    asyncio.run(scenario())


@pytest.mark.parametrize('scope', ['portfolio_analysis', 'risk'])
def test_specialist_cached_reads_recheck_generation_and_deadline(scope):
    async def scenario():
        collector = service()
        runtime = OptionsMCP(Mock(), portfolio_service=collector)
        cap = Capability(42, None, 'test', time.monotonic()+65, scope=scope,
            session_generation='g', risk_policy=RiskPolicy(revision=0))
        await runtime._read(cap)
        collector.assert_generation.side_effect = ValueError('stale')
        with pytest.raises(ValueError, match='stale'):
            await runtime._read(cap)
        collector.assert_generation.side_effect = None
        cap.deadline_monotonic = 0
        with pytest.raises(ValueError, match='deadline'):
            await runtime._read(cap)
        assert collector.fetch.call_count == 1
    asyncio.run(scenario())
