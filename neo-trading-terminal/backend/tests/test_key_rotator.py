import asyncio
import pytest
from agno.exceptions import ModelProviderError
from pydantic import SecretStr


def test_rotation_only_on_429_and_never_exposes_keys():
    from app.terminal.options_model import KeyRotator
    rotator = KeyRotator(SecretStr('primary-secret'), SecretStr('backup-secret'))
    assert rotator.next_key(ModelProviderError('quota', status_code=429)).get_secret_value() == 'backup-secret'
    assert rotator.next_key(ModelProviderError('quota', status_code=429)) is None
    assert 'secret' not in repr(rotator)
    other = KeyRotator(SecretStr('primary-secret'), SecretStr('backup-secret'))
    assert other.next_key(ModelProviderError('auth', status_code=401)) is None


def test_openai_retry_shares_request_budget(monkeypatch):
    from agno.models.openai import OpenAIChat
    from app.terminal.options_model import BoundedOpenAIChat, KeyRotator
    calls = []
    async def invoke(self, *args, **kwargs):
        calls.append(self.api_key)
        if len(calls) == 1:
            raise ModelProviderError('quota', status_code=429)
        from types import SimpleNamespace
        return SimpleNamespace(response_usage=SimpleNamespace(output_tokens=2))
    monkeypatch.setattr(OpenAIChat, 'ainvoke', invoke)
    async def scenario():
        model = BoundedOpenAIChat(api_key='primary', key_rotator=KeyRotator(SecretStr('primary'), SecretStr('backup')))
        await model.ainvoke()
        assert calls == ['primary', 'backup']
        assert model.requests_remaining == 1
    asyncio.run(scenario())


def test_gemini_retry_shares_request_budget(monkeypatch):
    from agno.models.google import Gemini
    from app.terminal.options_gemini import BoundedGemini
    from app.terminal.options_model import KeyRotator
    from types import SimpleNamespace
    calls = []
    async def invoke(self, *args, **kwargs):
        calls.append(self.api_key)
        if len(calls) == 1:
            raise ModelProviderError('quota', status_code=429)
        return SimpleNamespace(response_usage=SimpleNamespace(output_tokens=2, reasoning_tokens=0))
    monkeypatch.setattr(Gemini, 'ainvoke', invoke)
    async def scenario():
        model = BoundedGemini(api_key='primary', key_rotator=KeyRotator(SecretStr('primary'), SecretStr('backup')))
        await model.ainvoke()
        assert calls == ['primary', 'backup']
        assert model.requests_remaining == 1
    asyncio.run(scenario())
