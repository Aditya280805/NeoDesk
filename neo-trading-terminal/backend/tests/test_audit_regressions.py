import asyncio
from types import SimpleNamespace

import pytest

from app.terminal.agent_harness import RequestHarness, bounded_invoke, harness_context
from app.terminal.unified_chat import RoutingLimiter


def test_router_admission_shares_explicit_capacity():
    from threading import Lock
    from collections import deque
    from fastapi import HTTPException
    service = SimpleNamespace(guard=Lock(), active={1}, recent=deque(), refresh_active=set(),
                              mcp=SimpleNamespace(pending={}))
    limiter = RoutingLimiter(service)
    with pytest.raises(HTTPException):
        limiter.enter(1)
    service.active.update({2, 3, 4})
    with pytest.raises(HTTPException):
        limiter.enter(5)


def test_quota_rejection_preserves_retry_and_records_estimates():
    from agno.exceptions import ModelProviderError
    async def scenario():
        h = RequestHarness()
        async def rejected(**kwargs):
            raise ModelProviderError(message='quota', status_code=429)
        async def success(**kwargs):
            return SimpleNamespace(response_usage=SimpleNamespace(output_tokens=1))
        with harness_context(h, 'specialist'):
            with pytest.raises(ModelProviderError):
                await bounded_invoke(rejected, 900, messages=[])
            await bounded_invoke(success, 900, messages=[])
        assert h.attempts == 2
        assert h.stages['specialist'].generation_spent == 1
        assert h.trace()['stages']['specialist']['input_token_estimate'] > 0
    asyncio.run(scenario())


def test_parent_admission_is_retained_until_pending_worker_finishes():
    from app.terminal.options_agent import OptionsAgent
    from threading import Lock
    from collections import deque
    async def scenario():
        service = OptionsAgent.__new__(OptionsAgent)
        worker = asyncio.create_task(asyncio.sleep(0.01))
        service.guard, service.active, service.recent = Lock(), {1}, deque()
        service.refresh_active, service.workers = set(), {1: {worker}}
        service.mcp = SimpleNamespace(pending={})
        limiter = RoutingLimiter(service)
        limiter.leave(1)
        assert 1 in service.active
        await worker
        await asyncio.sleep(0)
        assert 1 not in service.active
    asyncio.run(scenario())


def test_trace_write_failure_emits_sanitized_warning(caplog):
    from app.terminal.unified_chat import _record_parent_run
    import time
    def broken(*args):
        raise RuntimeError('secret-must-not-be-logged')
    _record_parent_run(SimpleNamespace(record_run=broken), 1, 'run', 'failed', time.monotonic(), {})
    assert 'Parent run trace write failed' in caplog.text
    assert 'secret-must-not-be-logged' not in caplog.text


def test_openai_backup_key_retry_works_inside_parent_harness(monkeypatch):
    from agno.exceptions import ModelProviderError
    from agno.models.openai import OpenAIChat
    from pydantic import SecretStr
    from app.terminal.options_model import BoundedOpenAIChat, KeyRotator
    calls = []
    async def sdk(self, **kwargs):
        calls.append(self.api_key)
        if len(calls) == 1:
            raise ModelProviderError(message='quota', status_code=429)
        return SimpleNamespace(response_usage=SimpleNamespace(output_tokens=2))
    monkeypatch.setattr(OpenAIChat, 'ainvoke', sdk)
    async def scenario():
        harness = RequestHarness()
        model = BoundedOpenAIChat(api_key='primary', key_rotator=KeyRotator(
            SecretStr('primary'), SecretStr('backup')))
        with harness_context(harness, 'specialist'):
            await model.ainvoke(messages=[])
        assert calls == ['primary', 'backup']
        assert harness.attempts == 2
        assert harness.stages['specialist'].generation_spent == 2
    asyncio.run(scenario())
