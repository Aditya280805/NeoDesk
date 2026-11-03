import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from agno.models.message import Message


def test_completion_budget_shrinks_across_requests_and_stops_at_zero():
    from app.terminal.options_model import BoundedOpenAIChat

    async def scenario():
        limits = []
        def respond(request):
            limit = json.loads(request.content)['max_completion_tokens']
            limits.append(limit)
            return httpx.Response(200, json={'id': 'budget', 'created': 1, 'object': 'chat.completion',
                'model': 'gpt-4.1-mini', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': limit if len(limits) == 2 else 600, 'total_tokens': 610}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            model = BoundedOpenAIChat(id='gpt-4.1-mini', async_client=AsyncOpenAI(api_key='fixture', http_client=http))
            for _ in range(2):
                await model.ainvoke(messages=[Message(role='user', content='test')], assistant_message=Message(role='assistant'))
            with pytest.raises(ValueError, match='budget'):
                await model.ainvoke(messages=[], assistant_message=Message(role='assistant'))
        assert limits == [900, 300]
    asyncio.run(scenario())
