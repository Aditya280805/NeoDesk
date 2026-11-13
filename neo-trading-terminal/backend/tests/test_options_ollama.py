import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.terminal.options_model import BoundedOllamaChat, build_model, check_ollama_health, provider_settings
from app.terminal.server import create_app


def test_default_provider_points_to_local_ollama_qwen_specs():
    config = Settings(_env_file=None)
    settings = provider_settings(config)
    assert settings.configured and settings.provider == 'ollama'
    assert settings.model == 'qwen3.5:9b-q4_K_M'
    model = build_model(config)
    assert model.base_url == 'http://localhost:11434/v1'
    assert model.id == 'qwen3.5:9b-q4_K_M'
    assert model.api_key == 'ollama'
    assert model.reasoning_effort == 'none'
    assert model.key_rotator is None
    assert model.max_retries == 0
    assert config.options_agent_stream is True
    params = model.get_request_params()
    assert params['max_tokens'] == 4096
    assert 'max_completion_tokens' not in params


def test_local_model_never_uses_cloud_fallback():
    config = Settings(_env_file=None, options_agent_provider='ollama', gemini_api_key='synthetic', openai_api_key='synthetic')
    assert provider_settings(config).provider == 'ollama'
    model = build_model(config)
    assert model.base_url == 'http://localhost:11434/v1'
    assert model.id == 'qwen3.5:9b-q4_K_M'


def test_non_loopback_ollama_base_url_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_base_url='https://example.com/v1')


def test_local_http_roundtrip_has_bounded_generation_and_schema():
    from openai import AsyncOpenAI
    from agno.models.message import Message
    from app.terminal.agent_harness import RequestHarness, harness_context

    async def scenario():
        requests = []
        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            assert str(request.url).startswith('http://localhost:11434/v1/')
            return httpx.Response(200, json={'id': 'local', 'created': 1, 'object': 'chat.completion',
                'model': 'qwen3.5:9b-q4_K_M', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '{}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 5, 'total_tokens': 8}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = AsyncOpenAI(api_key='ollama', base_url='http://localhost:11434/v1', http_client=http)
            model = BoundedOllamaChat(id='qwen3.5:9b-q4_K_M', async_client=client)
            h = RequestHarness()
            with harness_context(h, 'specialist'):
                await model.ainvoke(messages=[Message(role='user', content='test')],
                    assistant_message=Message(role='assistant'), response_format={'type': 'json_object'})
            assert requests[0]['max_tokens'] == 4096
            assert 'max_completion_tokens' not in requests[0]
            assert requests[0]['response_format'] == {'type': 'json_object'}
            assert h.stages['specialist'].generation_spent == 5
    asyncio.run(scenario())


def test_local_http_streaming_roundtrip_tracks_usage_and_budget():
    from openai import AsyncOpenAI
    from agno.models.message import Message
    from app.terminal.agent_harness import RequestHarness, harness_context

    async def scenario():
        requests = []
        sse_body = (
            'data: {"id":"s1","object":"chat.completion.chunk","created":1,"model":"qwen3.5:9b-q4_K_M","choices":[{"index":0,"delta":{"role":"assistant","content":"{\\"answer\\":"},"finish_reason":null}]}\n\n'
            'data: {"id":"s1","object":"chat.completion.chunk","created":1,"model":"qwen3.5:9b-q4_K_M","choices":[{"index":0,"delta":{"content":"\\"ok\\"}"},"finish_reason":"stop"}]}\n\n'
            'data: {"id":"s1","object":"chat.completion.chunk","created":1,"model":"qwen3.5:9b-q4_K_M","choices":[],"usage":{"prompt_tokens":4,"completion_tokens":7,"total_tokens":11}}\n\n'
            'data: [DONE]\n\n'
        ).encode('utf-8')

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            assert str(request.url).startswith('http://localhost:11434/v1/')
            assert body['stream'] is True
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=sse_body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = AsyncOpenAI(api_key='ollama', base_url='http://localhost:11434/v1', http_client=http)
            model = BoundedOllamaChat(id='qwen3.5:9b-q4_K_M', async_client=client)
            h = RequestHarness()
            chunks = []
            with harness_context(h, 'specialist'):
                async for delta in model.ainvoke_stream(
                    messages=[Message(role='user', content='stream test')],
                    assistant_message=Message(role='assistant'),
                    response_format={'type': 'json_object'},
                ):
                    if delta.content:
                        chunks.append(delta.content)
            assert ''.join(chunks) == '{"answer":"ok"}'
            assert requests[0]['max_tokens'] == 4096
            assert 'max_completion_tokens' not in requests[0]
            assert model.completion_remaining == 4089
            assert h.stages['specialist'].generation_spent == 7

    asyncio.run(scenario())


def test_ollama_health_check_ok_missing_and_unreachable():
    config = Settings(_env_file=None)

    async def scenario():
        def ok_handler(request):
            assert str(request.url) == 'http://localhost:11434/api/tags'
            return httpx.Response(200, json={'models': [{'name': 'qwen3.5:9b-q4_K_M'}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(ok_handler)) as http:
            res = await check_ollama_health(config, http_client=http)
            assert res['healthy'] is True
            assert res['status'] == 'ok'
            assert res['model_available'] is True
            assert res['url'] == 'http://localhost:11434/api/tags'

        def missing_handler(request):
            return httpx.Response(200, json={'models': [{'name': 'other:latest'}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(missing_handler)) as http:
            res = await check_ollama_health(config, http_client=http)
            assert res['healthy'] is False
            assert res['status'] == 'missing_model'
            assert res['model_available'] is False

        def error_handler(request):
            raise httpx.ConnectError('connection refused', request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(error_handler)) as http:
            res = await check_ollama_health(config, http_client=http)
            assert res['healthy'] is False
            assert res['status'] == 'unreachable'

    asyncio.run(scenario())


def test_startup_health_check_and_streaming_chat_endpoint(tmp_path, monkeypatch):
    from openai import AsyncOpenAI

    startup_calls = []

    async def fake_tags_get(self, url, **kwargs):
        startup_calls.append(str(url))
        return httpx.Response(200, json={'models': [{'name': 'qwen3.5:9b-q4_K_M'}]})

    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_tags_get)

    def stream_transport_factory():
        def respond(request):
            body = json.loads(request.content)
            assert body['model'] == 'qwen3.5:9b-q4_K_M'
            assert body['stream'] is True
            assert body['max_tokens'] == 4096
            msg = next(m['content'] for m in body['messages'] if m['role'] == 'user' and 'current_snapshot' in m['content'])
            snap_id = json.loads(msg)['current_snapshot']['snapshot_id']
            answer_json = json.dumps({'answer': 'PCR is 1.5 based on snapshot.', 'snapshot_ids': [snap_id]})
            midpoint = len(answer_json) // 2
            chunks = [
                json.dumps({'id': 'chat1', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'qwen3.5:9b-q4_K_M',
                            'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': answer_json[:midpoint]}, 'finish_reason': None}]}),
                json.dumps({'id': 'chat1', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'qwen3.5:9b-q4_K_M',
                            'choices': [{'index': 0, 'delta': {'content': answer_json[midpoint:]}, 'finish_reason': 'stop'}]}),
                json.dumps({'id': 'chat1', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'qwen3.5:9b-q4_K_M',
                            'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 12, 'total_tokens': 22}}),
            ]
            sse = ''.join(f'data: {c}\n\n' for c in chunks) + 'data: [DONE]\n\n'
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=sse.encode('utf-8'))

        return AsyncOpenAI(api_key='ollama', base_url='http://localhost:11434/v1', http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)), max_retries=0)

    monkeypatch.setattr('app.terminal.options_model.BoundedOpenAIChat.get_async_client', lambda self: stream_transport_factory())

    def leg(strike, price, oi):
        return {'instrument': {'symbol': f'NIFTY-{strike}', 'strikePrice': str(strike)},
                'quote': {'ltp': price, 'volume': 20}, 'openInterest': {'current': oi}}

    chain = {
        'common_data': {'expiryDt': '29Oct2026', 'mktLot': '65'},
        'call': [leg(24000, 110, 100), leg(24100, 60, 300)],
        'put': [leg(24000, 90, 200), leg(24100, 140, 400)],
    }

    app = create_app(Settings(_env_file=None, data_dir=tmp_path, environment='development',
                              app_password=None, kotak_consumer_key=None, options_mcp_port=0))
    monkeypatch.setattr(app.state.market, 'call', Mock(return_value=chain))

    with TestClient(app, headers={'X-NeoDesk': '1'}) as client:
        assert startup_calls == ['http://localhost:11434/api/tags']
        assert client.post('/api/auth/register', json={'email': 'ollama@example.com',
            'password': 'test-password-123', 'display_name': 'Ollama'}).status_code == 200
        status = client.get('/api/options-agent/status').json()
        assert status['provider'] == 'ollama'
        assert status['model'] == 'qwen3.5:9b-q4_K_M'
        assert status['streaming_enabled'] is True
        assert status['ollama_health']['healthy'] is True

        health = client.get('/api/options-agent/health').json()
        assert health['healthy'] is True and health['status'] == 'ok'

        with client.stream('POST', '/api/options-agent/chat/stream', json={'message': 'Summarize the chain'}) as resp:
            assert resp.status_code == 200
            assert resp.headers['content-type'].startswith('text/event-stream')
            raw = resp.read().decode('utf-8')
        assert 'event: delta' in raw
        assert 'event: completed' in raw
        completed_line = [line for line in raw.splitlines() if line.startswith('data: ')][-1]
        completed_payload = json.loads(completed_line[6:])
        assert completed_payload['answer'] == 'PCR is 1.5 based on snapshot.'
        assert completed_payload['snapshot_ids'] == [completed_payload['snapshot']['snapshot_id']]
