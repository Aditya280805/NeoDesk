import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import HTTPException


def test_unified_routes_to_correct_scoped_handler(monkeypatch):
    from app.terminal.unified_chat import UnifiedChatRequest, dispatch_unified
    from app.terminal.unified_chat import RoutingLimiter
    service = SimpleNamespace(config=None, routing_limiter=RoutingLimiter(), chat=AsyncMock(return_value={'answer':'chain'}), portfolio_chat=AsyncMock(return_value={'answer':'portfolio'}))
    monkeypatch.setattr('app.terminal.unified_chat.route_question', AsyncMock(return_value='portfolio'))
    result = asyncio.run(dispatch_unified(service, 42, UnifiedChatRequest(message='Show my holdings')))
    assert result['scope'] == 'portfolio'
    assert service.portfolio_chat.await_args.args[0] == 42
    service.chat.assert_not_awaited()


def test_unified_ambiguous_does_not_fetch_private_data(monkeypatch):
    from app.terminal.unified_chat import UnifiedChatRequest, dispatch_unified
    from app.terminal.unified_chat import RoutingLimiter
    service = SimpleNamespace(config=None, routing_limiter=RoutingLimiter(), chat=AsyncMock(), portfolio_chat=AsyncMock())
    monkeypatch.setattr('app.terminal.unified_chat.route_question', AsyncMock(return_value='clarify'))
    result = asyncio.run(dispatch_unified(service, 42, UnifiedChatRequest(message='What do you think?')))
    assert result['scope'] == 'clarify'
    service.chat.assert_not_awaited()
    service.portfolio_chat.assert_not_awaited()


def test_team_is_route_mode_and_has_no_private_tools(monkeypatch):
    from agno.team import Team, TeamMode
    from app.terminal.unified_chat import route_question, RouteAnswer
    from app.terminal.options_model import BoundedOpenAIChat
    model = BoundedOpenAIChat(api_key='fixture')
    monkeypatch.setattr('app.terminal.unified_chat.build_model', lambda config: model)
    async def run(self, question):
        assert self.mode == TeamMode.route
        assert len(self.members) == 3
        assert not self.tools
        assert all(not member.tools for member in self.members)
        return SimpleNamespace(content=RouteAnswer(scope='chain'))
    monkeypatch.setattr(Team, 'arun', run)
    assert asyncio.run(route_question(None, 'NIFTY option chain')) == 'chain'


def test_real_team_routes_using_fake_model_transport(monkeypatch):
    import json
    import httpx
    from openai import AsyncOpenAI
    from app.terminal.options_model import BoundedOpenAIChat
    from app.terminal.unified_chat import route_question
    requests = []
    async def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            tools = body.get('tools', [])
            assert len(tools) == 1
            name = tools[0]['function']['name']
            message = {'role':'assistant', 'content':None, 'tool_calls':[{'id':'route1', 'type':'function',
                'function':{'name':name, 'arguments':json.dumps({'member_id':'chain','task':'Classify this question'})}}]}
            reason = 'tool_calls'
        else:
            message = {'role':'assistant', 'content':'{"scope":"chain"}'}
            reason = 'stop'
        return httpx.Response(200, json={'id':'mock', 'object':'chat.completion', 'created':1,
            'model':'gpt-4.1-mini', 'choices':[{'index':0,'message':message,'finish_reason':reason}],
            'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            model = BoundedOpenAIChat(id='gpt-4.1-mini', api_key='fixture',
                async_client=AsyncOpenAI(api_key='fixture', http_client=http, max_retries=0))
            monkeypatch.setattr('app.terminal.unified_chat.build_model', lambda config: model)
            assert await route_question(None, 'Show the NIFTY option chain') == 'chain'
    asyncio.run(scenario())
    assert len(requests) >= 2


def test_endpoint_requires_user_and_dispatches_with_signed_in_identity(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.terminal.server import create_app
    import app.terminal.routers.options_agent as router
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, environment='test',
        app_password=SecretStr('a sufficiently long test password'), options_agent_enabled=False))
    dispatch = AsyncMock(return_value={'scope':'clarify','answer':'Choose a scope.'})
    monkeypatch.setattr(router, 'dispatch_unified', dispatch)
    with TestClient(app, headers={'X-NeoDesk':'1'}) as client:
        assert client.post('/api/options-agent/unified-chat', json={'message':'hello'}).status_code == 401
        registration = client.post('/api/auth/register', json={'email':'route@example.com',
            'password':'test-password-123', 'display_name':'Route tester'})
        assert registration.status_code == 200
        response = client.post('/api/options-agent/unified-chat', json={'message':'hello'})
        assert response.status_code == 200
        assert dispatch.await_args.args[1] == registration.json()['user']['id']
