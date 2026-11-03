"""Provider selection and native Gemini HTTP integration; no external calls."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.terminal.server import create_app
from app.auth.router import _clear_rate_limits
from app.terminal.options_agent import build_agent
from app.terminal.options_snapshot import OptionsContext, normalize_snapshot
from test_options_agent import chain


def test_gemini_key_alone_selects_gemini_and_never_uses_openai(tmp_path):
    from app.terminal.options_model import provider_settings
    config = Settings(_env_file=None, data_dir=tmp_path, gemini_api_key=SecretStr('gemini-fixture'))
    provider = provider_settings(config)
    assert provider.provider == 'gemini'
    assert provider.model == 'gemini-3.8-flash'
    assert provider.key_name == 'GEMINI_API_KEY'
    assert provider.configured and not provider.error


def test_explicit_provider_never_falls_back_to_other_paid_provider():
    from app.terminal.options_model import provider_settings
    config = Settings(_env_file=None, options_agent_provider='gemini', openai_api_key=SecretStr('openai-fixture'))
    provider = provider_settings(config)
    assert provider.provider == 'gemini' and not provider.configured
    assert provider.key_name == 'GEMINI_API_KEY'


def test_auto_prefers_gemini_when_both_keys_exist_and_openai_still_works():
    from app.terminal.options_model import provider_settings
    both = Settings(_env_file=None, gemini_api_key=SecretStr('google-fixture'), openai_api_key=SecretStr('openai-fixture'))
    assert provider_settings(both).provider == 'gemini'
    old = Settings(_env_file=None, openai_api_key=SecretStr('openai-fixture'))
    assert provider_settings(old).model == 'gpt-4.1-mini'


def test_incompatible_model_is_actionable_configuration_error():
    from app.terminal.options_model import provider_settings
    config = Settings(_env_file=None, gemini_api_key=SecretStr('google-fixture'), options_agent_model='gpt-4.1-mini')
    provider = provider_settings(config)
    assert not provider.configured
    assert 'OPTIONS_AGENT_MODEL' in provider.error
    assert 'google-fixture' not in provider.error


def test_gemini_status_and_missing_key_are_provider_specific(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, environment='test',
                             options_agent_provider='gemini', options_mcp_port=0))
    _clear_rate_limits()
    with TestClient(app, headers={'X-NeoDesk': '1'}) as client:
        assert client.post('/api/auth/register', json={'email':'gemini@example.com',
            'password':'test-password-123','display_name':'Gemini'}).status_code == 200
        status = client.get('/api/options-agent/status').json()
        assert status['provider'] == 'gemini'
        assert status['model'] == 'gemini-3.8-flash'
        assert status['api_key_env'] == 'GEMINI_API_KEY'
        reply = client.post('/api/options-agent/chat', json={'message':'Explain OI'})
        assert reply.status_code == 503
        assert 'GEMINI_API_KEY' in reply.text and 'OPENAI_API_KEY' not in reply.text


def test_gemini_budget_includes_thinking_and_preserves_provider_total():
    from google import genai
    from google.genai import types
    from agno.models.message import Message
    from app.terminal.options_gemini import BoundedGemini

    async def scenario():
        limits = []
        def respond(request):
            payload = json.loads(request.content)
            limits.append(payload['generationConfig']['maxOutputTokens'])
            assert payload['generationConfig']['thinkingConfig']['thinking_level'] == 'LOW'
            return httpx.Response(200, json={'candidates': [{'content': {'role':'model','parts':[{'text':'OK'}]}, 'finishReason':'STOP'}],
                'usageMetadata': {'promptTokenCount': 50, 'candidatesTokenCount': 100,
                                  'thoughtsTokenCount': 200, 'totalTokenCount': 350}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            sdk = genai.Client(api_key='fixture', http_options=types.HttpOptions(httpx_async_client=http))
            model = BoundedGemini(id='gemini-3.8-flash', client=sdk, generation_remaining=600, thinking_level='low')
            try:
                for _ in range(2):
                    response = await model.ainvoke(messages=[Message(role='user', content='Hello')], assistant_message=Message(role='assistant'))
                    assert response.response_usage.total_tokens == 350
                with pytest.raises(ValueError, match='budget'):
                    await model.ainvoke(messages=[], assistant_message=Message(role='assistant'))
            finally:
                await sdk.aio.aclose()
                sdk.close()
        assert limits == [600, 300]
    asyncio.run(scenario())


def test_gemini_missing_generation_usage_reserves_remaining_budget(monkeypatch):
    from types import SimpleNamespace
    from agno.models.google import Gemini
    from app.terminal.options_gemini import BoundedGemini

    async def scenario():
        calls = []
        async def no_usage(self, *args, **kwargs):
            calls.append(True)
            return SimpleNamespace(response_usage=SimpleNamespace(output_tokens=None, reasoning_tokens=None))
        monkeypatch.setattr(Gemini, 'ainvoke', no_usage)
        model = BoundedGemini(id='gemini-3.8-flash', generation_remaining=100)
        await model.ainvoke(messages=[], assistant_message=None)
        with pytest.raises(ValueError, match='budget'):
            await model.ainvoke(messages=[], assistant_message=None)
        assert len(calls) == 1
    asyncio.run(scenario())


def test_real_gemini_agent_mcp_cycle_without_external_network(tmp_path, monkeypatch):
    from google import genai
    from google.genai import types
    calls = []
    transport_errors = []
    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert str(request.url).endswith('/models/gemini-3.8-flash:generateContent')
        declarations = payload['tools'][0]['functionDeclarations']
        assert [d['name'] for d in declarations] == ['get_option_snapshot']
        assert 'NIFTY-24000' not in str(payload.get('systemInstruction', {}))
        generation = payload['generationConfig']
        assert generation['responseMimeType'] == 'application/json'
        assert 'snapshot_ids' in generation['responseSchema']['properties']
        if len(calls) == 1:
            parts = [{'functionCall': {'name':'get_option_snapshot','args':{},'id':'snapshot-call'},
                      'thoughtSignature': 'Zml4dHVyZQ=='}]
        else:
            calls_back = [part['functionCall'] for c in payload['contents'] for part in c['parts'] if 'functionCall' in part]
            assert calls_back and calls_back[0]['id'] == 'snapshot-call'
            responses = [part['functionResponse'] for c in payload['contents'] for part in c['parts'] if 'functionResponse' in part]
            assert responses and responses[0]['name'] == 'get_option_snapshot'
            assert responses[0]['id'] == 'snapshot-call'
            data = str(responses[0])
            assert 'put_call_ratio' in data and '1.5' in data
            prompt = next(part['text'] for c in payload['contents'] for part in c['parts']
                          if 'text' in part and 'current_snapshot' in part['text'])
            snapshot = json.loads(prompt)['current_snapshot']
            parts = [{'text': json.dumps({'answer':'Partial-chain ratio is 1.5. Exchange freshness is unverified.',
                                         'snapshot_ids':[snapshot['snapshot_id']]})}]
        return httpx.Response(200, json={'candidates':[{'content':{'role':'model','parts':parts},'finishReason':'STOP'}],
            'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':40,'thoughtsTokenCount':60,'totalTokenCount':200}})

    def send(request):
        try:
            return respond(request)
        except Exception as error:
            transport_errors.append(repr(error))
            raise
    sdk = genai.Client(api_key='gemini-fixture', http_options=types.HttpOptions(
        httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(send))))
    monkeypatch.setattr('app.terminal.options_gemini.BoundedGemini.get_client', lambda self: sdk)
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, environment='test',
        gemini_api_key=SecretStr('gemini-fixture'), options_mcp_port=0))
    monkeypatch.setattr(app.state.market, 'call', lambda *args, **kwargs: chain())
    _clear_rate_limits()
    with TestClient(app, headers={'X-NeoDesk':'1'}) as client:
        assert client.post('/api/auth/register', json={'email':'gemini-cycle@example.com',
            'password':'test-password-123','display_name':'Gemini cycle'}).status_code == 200
        reply = client.post('/api/options-agent/chat', json={'message':'Explain the ratio'})
        assert reply.status_code == 200, (reply.text, transport_errors)
        body = reply.json()
        assert body['snapshot_ids'] == [body['snapshot']['snapshot_id']]
        assert '1.5' in body['answer']
        record = client.get('/api/options-agent/runs/'+body['run_id']).json()
        assert record['detail']['provider'] == 'gemini'
        assert record['detail']['tokens']['total_tokens'] == 400
        assert record['detail']['tokens']['reasoning_tokens'] == 120
    asyncio.run(sdk.aio.aclose())
    sdk.close()
    assert len(calls) == 2


def test_gemini_sdk_does_not_retry_quota_errors_and_closes_clients(monkeypatch):
    from google import genai
    from agno.models.message import Message
    from agno.exceptions import ModelProviderError
    from app.terminal.options_gemini import BoundedGemini
    from app.terminal.options_model import options_run

    async def scenario():
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(429, json={'error':{'code':429, 'status':'RESOURCE_EXHAUSTED', 'message':'fixture quota'}})
        clients = []
        client_class = genai.Client
        def create(**kwargs):
            assert kwargs['vertexai'] is False and kwargs['enterprise'] is False
            assert kwargs['http_options'].timeout == 30000
            assert kwargs['http_options'].retry_options.attempts == 1
            kwargs['http_options'].async_client_args = {'transport': httpx.MockTransport(respond)}
            sdk = client_class(**kwargs)
            clients.append(sdk)
            return sdk
        monkeypatch.setattr('app.terminal.options_gemini.genai.Client', create)
        model = BoundedGemini(id='gemini-3.8-flash', api_key='fixture', timeout=30)
        log_context = options_run.set(True)
        try:
            with pytest.raises(ModelProviderError) as error:
                await model.ainvoke(messages=[Message(role='user',content='Hello')], assistant_message=Message(role='assistant'))
            assert error.value.status_code == 429
        finally:
            await model.aclose()
            options_run.reset(log_context)
        assert len(calls) == 1 and model.client is None
        assert clients[0]._api_client._async_httpx_client.is_closed
    asyncio.run(scenario())
