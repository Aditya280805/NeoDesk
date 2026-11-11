from app.core.config import Settings
from app.terminal.options_model import build_model, provider_settings


def test_local_provider_needs_no_secret_and_uses_loopback():
    config = Settings(_env_file=None, options_agent_provider='ollama', options_agent_model='qwen3:4b')
    settings = provider_settings(config)
    assert settings.configured and settings.provider == 'ollama'
    model = build_model(config)
    assert model.base_url == 'http://127.0.0.1:11434/v1'
    assert model.id == 'qwen3:4b'
    assert model.key_rotator is None
    assert model.max_retries == 0
    params = model.get_request_params()
    assert params['max_tokens'] == 900
    assert 'max_completion_tokens' not in params


def test_local_model_never_uses_cloud_fallback():
    config = Settings(_env_file=None, options_agent_provider='ollama', gemini_api_key='synthetic', openai_api_key='synthetic')
    assert provider_settings(config).provider == 'ollama'
    assert build_model(config).base_url.startswith('http://127.0.0.1:')


def test_local_http_roundtrip_has_bounded_generation_and_schema():
    import asyncio
    import json
    import httpx
    from openai import AsyncOpenAI
    from agno.models.message import Message
    from app.terminal.options_model import BoundedOllamaChat
    from app.terminal.agent_harness import RequestHarness, harness_context
    async def scenario():
        requests = []
        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            assert str(request.url).startswith('http://127.0.0.1:11434/v1/')
            return httpx.Response(200, json={'id': 'local', 'created': 1, 'object': 'chat.completion',
                'model': 'qwen3:4b', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '{}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 5, 'total_tokens': 8}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = AsyncOpenAI(api_key='ollama', base_url='http://127.0.0.1:11434/v1', http_client=http)
            model = BoundedOllamaChat(id='qwen3:4b', async_client=client)
            h = RequestHarness()
            with harness_context(h, 'specialist'):
                await model.ainvoke(messages=[Message(role='user', content='test')],
                    assistant_message=Message(role='assistant'), response_format={'type': 'json_object'})
            assert requests[0]['max_tokens'] == 900
            assert 'max_completion_tokens' not in requests[0]
            assert requests[0]['response_format'] == {'type': 'json_object'}
            assert h.stages['specialist'].generation_spent == 5
    asyncio.run(scenario())
