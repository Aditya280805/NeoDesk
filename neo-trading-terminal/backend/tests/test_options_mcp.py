"""Real loopback MCP protocol, authentication and lifetime checks; no broker network."""
import asyncio
import socket
import threading
from unittest.mock import Mock

import httpx
import pytest

from app.terminal.options_snapshot import OptionsContext, SnapshotService
from test_options_agent import chain


def test_mcp_transport_is_private_scoped_cached_and_revocable():
    from app.terminal.options_mcp import OptionsMCP

    async def scenario():
        market = Mock()
        market.call.return_value = chain()
        runtime = OptionsMCP(SnapshotService(market), port=0)
        async with runtime.lifespan():
            assert runtime.ready
            async with httpx.AsyncClient() as http:
                assert (await http.post(runtime.url, json={})).status_code == 401
                assert (await http.post(runtime.url, headers={'Authorization': 'Bearer invalid'}, json={})).status_code == 401
            async with runtime.connection(42, OptionsContext(), 'run-42') as connection:
                tools = connection.tools
                names = list(tools.functions)
                assert names == ['get_option_snapshot']
                first = await connection.snapshot()
                second = await connection.snapshot()
                assert first['summary']['put_call_ratio'] == 1.5
                assert first['snapshot_id'] == second['snapshot_id']
                assert market.call.call_count == 1
                assert market.call.call_args.kwargs['user_id'] == 42
                token = connection.token
            async with httpx.AsyncClient() as http:
                assert (await http.post(runtime.url, headers={'Authorization': 'Bearer '+token}, json={})).status_code == 401
        assert not runtime.ready
        assert not runtime.capabilities

    asyncio.run(scenario())


def test_mcp_bind_failure_does_not_crash_website():
    from app.terminal.options_mcp import OptionsMCP

    async def scenario():
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            runtime = OptionsMCP(SnapshotService(Mock()), port=occupied.getsockname()[1])
            async with runtime.lifespan():
                assert not runtime.ready
                with pytest.raises(Exception, match='unavailable'):
                    async with runtime.connection(1, OptionsContext(), 'run'):
                        pass
    asyncio.run(scenario())


def test_mcp_expired_capability_and_out_of_context_arguments_are_rejected():
    from app.terminal.options_mcp import OptionsMCP

    async def scenario():
        market = Mock()
        market.call.return_value = chain()
        runtime = OptionsMCP(SnapshotService(market), port=0)
        async with runtime.lifespan():
            async with runtime.connection(7, OptionsContext(), 'run') as connection:
                result = await connection.tools.session.call_tool('get_option_snapshot', {'user_id': 999}, raise_on_error=False)
                assert result.is_error
                assert market.call.call_count == 0
                runtime.capabilities[connection.token].expires = 0
                async with httpx.AsyncClient() as http:
                    result = await http.post(runtime.url, headers={'Authorization': 'Bearer '+connection.token}, json={})
                    assert result.status_code == 401
    asyncio.run(scenario())


def test_mcp_tool_budget_and_origin_rejection():
    from app.terminal.options_mcp import OptionsMCP

    async def scenario():
        market = Mock()
        market.call.return_value = chain()
        runtime = OptionsMCP(SnapshotService(market), port=0)
        async with runtime.lifespan():
            async with runtime.connection(7, OptionsContext(), 'run') as connection:
                for _ in range(3):
                    await connection.snapshot()
                with pytest.raises(Exception):
                    await connection.snapshot()
                async with httpx.AsyncClient() as http:
                    result = await http.post(runtime.url, headers={'Authorization': 'Bearer '+connection.token,
                        'Origin': 'https://evil.example'}, json={})
                    assert result.status_code == 401
                assert market.call.call_count == 1
    asyncio.run(scenario())


def test_cancelled_broker_request_keeps_slot_until_worker_finishes():
    from app.terminal.options_mcp import OptionsMCP, Capability
    from time import monotonic

    async def scenario():
        started, release = threading.Event(), threading.Event()
        def fetch(*args, **kwargs):
            started.set()
            release.wait(2)
            return chain()
        runtime = OptionsMCP(SnapshotService(Mock(call=fetch)), port=0)
        task = asyncio.create_task(runtime._read(Capability(7, OptionsContext(), 'run', monotonic()+60)))
        try:
            async with asyncio.timeout(2):
                while not started.is_set():
                    await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert 7 in runtime.pending
            with pytest.raises(ValueError, match='already running'):
                await runtime._read(Capability(7, OptionsContext(), 'other', monotonic()+60))
        finally:
            release.set()
            await asyncio.gather(*runtime.pending.values(), return_exceptions=True)
        assert not runtime.pending
    asyncio.run(scenario())
