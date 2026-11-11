import asyncio
from types import SimpleNamespace

import pytest


def test_context_estimator_ignores_sdk_runtime_timers():
    from agno.models.message import Message
    from app.terminal.agent_harness import estimate_tokens
    message = Message(role='assistant', content='test')
    message.metrics.start_timer()
    assert estimate_tokens([message]) > 0

def test_attempts_and_unknown_usage_are_shared_across_models():
    from app.terminal.agent_harness import RequestHarness, harness_context, bounded_invoke, HarnessError
    async def scenario():
        harness = RequestHarness()
        async def invoke(**kwargs):
            return SimpleNamespace(response_usage=SimpleNamespace(output_tokens=1))
        with harness_context(harness, 'specialist'):
            for _ in range(3):
                await bounded_invoke(invoke, 900, messages=[])
            with pytest.raises(HarnessError, match='model_budget'):
                await bounded_invoke(invoke, 900, messages=[])
        assert harness.attempts == 3
        other = RequestHarness()
        async def unknown(**kwargs):
            return SimpleNamespace(response_usage=None)
        with harness_context(other, 'specialist'):
            await bounded_invoke(unknown, 900, messages=[])
            with pytest.raises(HarnessError, match='model_budget'):
                await bounded_invoke(unknown, 900, messages=[])
        assert other.stages['specialist'].generation_spent == 900
    asyncio.run(scenario())


def test_context_and_deadline_block_before_sdk_call():
    from app.terminal.agent_harness import RequestHarness, harness_context, bounded_invoke, HarnessError
    async def scenario():
        calls = []
        async def invoke(**kwargs):
            calls.append(1)
        for harness in (RequestHarness(deadline=0), RequestHarness(input_limit=1)):
            with harness_context(harness, 'specialist'):
                with pytest.raises(HarnessError):
                    await bounded_invoke(invoke, 900, messages=['x'*100])
        assert not calls
    asyncio.run(scenario())


def test_auto_stage_limits_and_tool_limits():
    from app.terminal.agent_harness import RequestHarness, HarnessError
    h = RequestHarness(auto=True)
    for stage in ('router', 'specialist'):
        for _ in range(3):
            ticket = h.reserve(stage, 900, 1)
            h.account(ticket, 1)
    assert h.attempts == 6
    with pytest.raises(HarnessError):
        h.reserve('router', 900, 1)
    for _ in range(3):
        h.read_tool()
    with pytest.raises(HarnessError, match='tool_budget'):
        h.read_tool()


def test_history_trimming_protects_required_evidence():
    from app.terminal.agent_harness import bounded_context, HarnessError
    base = {'evidence_id': 'fixed', 'limitations': ['unavailable'], 'question': 'current'}
    trimmed, history = bounded_context(base, ['x'*500, 'recent'], input_limit=100)
    assert trimmed == base and history == ['recent']
    with pytest.raises(HarnessError, match='context_budget'):
        bounded_context({'evidence': 'x'*1000}, [], input_limit=1)


def test_context_is_isolated_between_requests():
    from app.terminal.agent_harness import RequestHarness, harness_context, current_harness
    first, second = RequestHarness(), RequestHarness()
    with harness_context(first, 'router'):
        assert current_harness.get()[0] is first
        with harness_context(second, 'specialist'):
            assert current_harness.get()[0] is second
        assert current_harness.get()[0] is first
    assert current_harness.get() is None


def test_harness_settings_reject_impossible_context():
    from app.core.config import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret='synthetic', agent_input_token_estimate_limit=32000,
                 agent_context_token_limit=32768)


def test_provider_models_share_parent_budget(monkeypatch):
    from agno.models.openai import OpenAIChat
    from app.terminal.options_model import BoundedOpenAIChat
    from app.terminal.agent_harness import RequestHarness, harness_context, HarnessError
    calls = []
    async def sdk(self, **kwargs):
        calls.append(self.max_completion_tokens)
        return SimpleNamespace(response_usage=SimpleNamespace(output_tokens=1))
    monkeypatch.setattr(OpenAIChat, 'ainvoke', sdk)
    async def scenario():
        h = RequestHarness()
        with harness_context(h, 'specialist'):
            for _ in range(3):
                await BoundedOpenAIChat().ainvoke(messages=[])
            with pytest.raises(HarnessError):
                await BoundedOpenAIChat().ainvoke(messages=[])
        assert calls == [900, 899, 898]
    asyncio.run(scenario())


def test_gemini_accounting_includes_reasoning_and_cancellation_reserves_budget():
    from app.terminal.agent_harness import RequestHarness, harness_context, bounded_invoke
    async def scenario():
        h = RequestHarness()
        async def gemini(**kwargs):
            return SimpleNamespace(response_usage=SimpleNamespace(output_tokens=10, reasoning_tokens=30))
        with harness_context(h, 'specialist'):
            await bounded_invoke(gemini, 4096, reasoning=True, messages=[])
        assert h.stages['specialist'].generation_spent == 40
        cancelled = RequestHarness()
        async def cancel(**kwargs):
            raise asyncio.CancelledError()
        with harness_context(cancelled, 'specialist'):
            with pytest.raises(asyncio.CancelledError):
                await bounded_invoke(cancel, 900, messages=[])
        assert cancelled.stages['specialist'].generation_spent == 900
        assert cancelled.stages['specialist'].unknown_usage == 1
    asyncio.run(scenario())
