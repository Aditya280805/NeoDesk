"""Runtime controls: authenticated identity, budgets, evidence and diagnostics."""
import asyncio
import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_options_agent import app, client, module  # shared isolated API fixtures


def test_exception_during_application_lifespan_closes_private_listener(app):
    async def scenario():
        with pytest.raises(RuntimeError, match='fixture shutdown'):
            async with app.router.lifespan_context(app):
                assert app.state.options_agent.mcp.ready
                raise RuntimeError('fixture shutdown')
        assert not app.state.options_agent.mcp.ready
    asyncio.run(scenario())


def test_shared_login_cannot_use_an_implicit_user(app):
    from fastapi.testclient import TestClient
    with TestClient(app, headers={'X-NeoDesk': '1'}) as c:
        assert c.get('/api/options-agent/status').status_code == 401
        assert c.post('/api/options-agent/snapshot', json={}).status_code == 401


def test_snapshot_refresh_has_independent_throttle(client):
    assert client.post('/api/options-agent/snapshot', json={}).status_code == 200
    assert client.post('/api/options-agent/snapshot', json={}).status_code == 429
    assert client.post('/api/options-agent/chat', json={'message': 'Explain OI'}).status_code == 200


def test_invalid_evidence_fails_and_records_sanitized_failure(client, app):
    module.build_agent.side_effect = lambda *args: SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(
        content={'answer': 'Wrong evidence', 'snapshot_ids': ['invented']})))
    result = client.post('/api/options-agent/chat', json={'message': 'Explain OI'})
    assert result.status_code == 503
    run_id = result.headers['X-Options-Run-Id']
    assert client.get('/api/options-agent/runs/'+run_id).json()['status'] == 'failed'
    with app.state.store.connect() as db:
        assert db.execute('SELECT count(*) FROM option_chat_turns').fetchone()[0] == 0
        row = db.execute('SELECT status,detail FROM option_agent_runs').fetchone()
        assert row[0] == 'failed'
        assert 'output' in row[1] and 'test-key' not in row[1]


def test_deadline_releases_agent_and_records_timeout(client, app):
    async def slow(*args):
        await asyncio.sleep(1)
    app.state.options_agent.deadline_seconds = .1
    module.build_agent.side_effect = lambda *args: SimpleNamespace(arun=slow)
    result = client.post('/api/options-agent/chat', json={'message': 'Explain OI'})
    assert result.status_code == 504
    # A timed-out request retains admission until its tracked trace worker ends.
    async def settled():
        await asyncio.gather(*app.state.options_agent.workers.get(1, ()), return_exceptions=True)
        await asyncio.sleep(0)
    client.portal.call(settled)
    assert app.state.options_agent.active == set()
    with app.state.store.connect() as db:
        assert db.execute('SELECT status FROM option_agent_runs').fetchone()[0] == 'timeout'


def test_run_diagnostics_are_user_scoped(client, app):
    reply = client.post('/api/options-agent/chat', json={'message': 'Explain OI'}).json()
    run = client.get('/api/options-agent/runs/'+reply['run_id']).json()
    assert run['status'] == 'completed'
    assert run['detail']['snapshot_id'] == reply['snapshot']['snapshot_id']
    assert run['detail']['tool_calls'] == 1
    result = client.post('/api/auth/register', json={'email': 'other@example.com',
        'password': 'test-password-123', 'display_name': 'Other'})
    assert result.status_code == 200
    assert client.get('/api/options-agent/runs/'+reply['run_id']).status_code == 404


@pytest.mark.parametrize('code,expected', [(429, 'quota'), (401, 'GEMINI_API_KEY'), (403, 'permission')])
def test_gemini_provider_errors_are_actionable_and_redacted(client, app, code, expected):
    from agno.exceptions import ModelProviderError
    from pydantic import SecretStr
    app.state.config.options_agent_provider = 'gemini'
    app.state.config.gemini_api_key = SecretStr('gemini-fixture-secret')
    module.build_agent.side_effect = ModelProviderError(message='gemini-fixture-secret', status_code=code)
    result = client.post('/api/options-agent/chat', json={'message':'Explain OI'})
    assert result.status_code == 503
    assert expected in result.text
    assert 'gemini-fixture-secret' not in result.text
    record = client.get('/api/options-agent/runs/'+result.headers['X-Options-Run-Id']).json()
    assert record['status'] == 'failed'
    assert record['detail']['provider'] == 'gemini'
    assert record['detail']['failure_reason'].startswith('provider_')
    assert 'gemini-fixture-secret' not in json.dumps(record)
