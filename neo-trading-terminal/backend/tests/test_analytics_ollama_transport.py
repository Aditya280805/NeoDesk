"""Real SDK wire contract, mocked HTTP only; no model quality claims."""
import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from openai import AsyncOpenAI

from app.core.config import Settings
from app.terminal.analytics_coordinator import classify
from app.terminal.analytics_runtime import TurnBudget
from app.terminal.options_model import build_model


@pytest.mark.parametrize('provider,expected_role',[('ollama','system'),('openai','developer')])
def test_router_system_rules_reach_local_model_in_supported_role(tmp_path,provider,expected_role):
    async def run():
        requests=[]
        def respond(request):
            body=json.loads(request.content)
            requests.append(body)
            return httpx.Response(200,json={'id':'fixture','created':1,'object':'chat.completion','model':'fixture',
                'choices':[{'index':0,'message':{'role':'assistant','content':'{"route":"OPTIONS"}'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':100,'completion_tokens':8,'total_tokens':108}})
        config=Settings(_env_file=None,data_dir=tmp_path,options_agent_provider=provider,openai_api_key='synthetic')
        model=build_model(config)
        model.async_client=AsyncOpenAI(base_url='http://localhost:11434/v1',api_key='synthetic',max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        with patch('app.terminal.analytics_coordinator.build_model',return_value=model):
            result=await classify(config,'Explain option-chain open interest.',TurnBudget())
        assert result.delegated_agents==('options_trading_analysis',)
        assert len(requests)==1
        assert [message['role'] for message in requests[0]['messages']]==[expected_role,'user']
        assert 'Choose exactly one route label' in requests[0]['messages'][0]['content']
        assert requests[0]['response_format']['json_schema']['name']=='RouterIntent'
        assert not requests[0].get('tools')
    asyncio.run(run())
