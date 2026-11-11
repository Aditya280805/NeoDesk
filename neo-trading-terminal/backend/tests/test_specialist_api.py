import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.terminal.agent_registry import AGENT_REGISTRY
from app.terminal.options_snapshot import OptionsContext
from test_portfolio_agent import app, client


def test_risk_specialist_api_isolated_and_persisted(client, app, monkeypatch):
    captured = []
    def build(config, snapshot, tools, *, scope):
        assert scope.agent_id == 'portfolio_risk'
        assert set(snapshot) == {'evidence_id', 'risk_report'}
        async def run(prompt):
            captured.append(json.loads(prompt))
            return SimpleNamespace(content={'answer': 'Existing checks have limitations.',
                'evidence_ids': [snapshot['evidence_id']],
                'risk_report_ids': [snapshot['risk_report']['report_id']]})
        return SimpleNamespace(arun=run)
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_risk', build)
    response = client.post('/api/options-agent/portfolio/risk/chat', json={'message': 'Explain risk'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['agent_id'] == 'portfolio_risk' and body['parent_run_id']
    assert body['risk_snapshot']['evidence_id'] == body['evidence_ids'][0]
    assert 'sections' not in body['risk_snapshot']
    assert 'current_risk_report' in captured[0]
    history = client.get('/api/options-agent/conversations/'+body['conversation_id']).json()
    assert history['context']['agent_id'] == 'portfolio_risk'
    assert history['turns'][0]['risk_snapshot'] == body['risk_snapshot']
    record = client.get('/api/options-agent/runs/'+body['run_id']).json()['detail']
    assert record['harness']['tool_reads'] == 1
    followup = client.post('/api/options-agent/portfolio/risk/chat', json={'message':'Explain limitations',
        'conversation_id':body['conversation_id']})
    assert followup.status_code == 200, followup.text
    assert len(captured[1]['previous_conversation']) == 1
    assert client.post('/api/options-agent/portfolio/chat', json={'message':'switch',
        'conversation_id':body['conversation_id']}).status_code == 409


def test_risk_endpoint_rejects_unauthenticated(app):
    app.state.config.app_password = SecretStr('synthetic-password')
    with TestClient(app) as other:
        assert other.post('/api/options-agent/portfolio/risk/chat', json={'message':'risk'}).status_code == 401


def test_legacy_conversation_rejected_before_risk_fetch(client, app):
    # Seed legacy portfolio conversation
    cid = str(uuid4())
    legacy_context = {'schema_version': 'portfolio.v1', 'scope': 'portfolio'}
    legacy_snap = {'evidence_id': str(uuid4()), 'schema_version': 'portfolio.v1', 'sections': {}, 'summary': {}}
    with app.state.store.connect() as db:
        db.execute('INSERT INTO option_chat_conversations VALUES (?,?,?,?)',
                   (cid, 1, json.dumps(legacy_context), '2026-01-01T00:00:00Z'))
        db.execute('INSERT INTO option_chat_turns(conversation_id,user_id,message,answer,evidence,created_at) VALUES (?,?,?,?,?,?)',
                   (cid, 1, 'old msg', 'old ans', json.dumps(legacy_snap), '2026-01-01T00:00:00Z'))
    before = app.state.market.call.call_count
    result = client.post('/api/options-agent/portfolio/risk/chat', json={'message':'risk',
        'conversation_id': cid})
    assert result.status_code == 409
    assert result.json()['detail']['code'] == 'conversation_scope_changed'
    assert app.state.market.call.call_count == before
    # Continuing via portfolio analysis also fails with 409 conversation_scope_changed
    cont_port = client.post('/api/options-agent/portfolio/chat', json={'message': 'portfolio', 'conversation_id': cid})
    assert cont_port.status_code == 409
    assert cont_port.json()['detail']['code'] == 'conversation_scope_changed'
    assert app.state.market.call.call_count == before


def test_risk_specialist_invalid_citation_never_persists(client, app, monkeypatch):
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_risk', lambda *a, **kw:
        SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content={'answer':'bad',
            'evidence_ids':['invalid'], 'risk_report_ids':[]}))))
    response = client.post('/api/options-agent/portfolio/risk/chat', json={'message':'risk'})
    assert response.status_code == 503
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM option_chat_turns').fetchone()[0] == 0


def test_portfolio_analysis_specialist_api_isolated(client, app, monkeypatch):
    captured = []
    def build(config, snapshot, tools, *, scope):
        assert scope.agent_id == 'portfolio_analysis'
        assert 'risk_report' not in snapshot
        assert 'risk_inputs' not in snapshot
        assert 'sections' in snapshot
        async def run(prompt):
            captured.append(json.loads(prompt))
            return SimpleNamespace(content={'answer': 'Holdings and funds are available.',
                'evidence_ids': [snapshot['evidence_id']]})
        return SimpleNamespace(arun=run)
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_analysis', build)
    response = client.post('/api/options-agent/portfolio/chat', json={'message': 'Summarize holdings'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['agent_id'] == 'portfolio_analysis'
    assert body['parent_run_id']
    assert body['evidence_ids'] == [body['portfolio_snapshot']['evidence_id']]
    assert 'risk_report_ids' not in body
    assert 'risk_report' not in body['portfolio_snapshot']
    assert 'current_portfolio_snapshot' in captured[0]
    assert 'risk_report' not in captured[0]['current_portfolio_snapshot']
    # Model returning risk_report_ids must be rejected by PortfolioAnalysisAnswer
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_analysis', lambda *a, **kw:
        SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content={'answer': 'illegal risk',
            'evidence_ids': [body['evidence_ids'][0]], 'risk_report_ids': [str(uuid4())]}))))
    bad = client.post('/api/options-agent/portfolio/chat', json={'message': 'Illegal'})
    assert bad.status_code == 503
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM portfolio_risk_reports').fetchone()[0] == 0


def test_chain_and_explain_use_registered_specialist_no_external_tools(client, app, monkeypatch):
    chain_captured = []
    def build_chain(config, snapshot, tools, *, scope):
        assert scope.agent_id == 'options_trading_analysis'
        assert len(tools) == 1  # exactly one MCP tool, no external tools
        async def run(prompt):
            chain_captured.append(json.loads(prompt))
            return SimpleNamespace(content={'answer': 'Put/call ratio is 1.5.',
                'snapshot_ids': [snapshot['snapshot_id']]})
        return SimpleNamespace(arun=run)
    monkeypatch.setitem(AGENT_REGISTRY, 'options_trading_analysis', build_chain)
    from test_options_agent import chain as chain_fixture
    monkeypatch.setattr(app.state.market, 'call', Mock(return_value=chain_fixture()))
    response = client.post('/api/options-agent/chat', json={'message': 'Analyze chain'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['agent_id'] == 'options_trading_analysis'
    assert body['parent_run_id']
    assert body['snapshot_ids'] == [body['snapshot']['snapshot_id']]
    assert 'current_snapshot' in chain_captured[0]

    # Report explanation
    from test_options_report_chat import seed
    report_id = seed(app, 'scan')
    report_captured = []
    def build_report(config, snapshot, tools, *, scope):
        assert scope.agent_id == 'options_trading_analysis'
        assert len(tools) == 1
        async def run(prompt):
            report_captured.append(json.loads(prompt))
            return SimpleNamespace(content={'answer': 'Historical observation age is 305 days.',
                'report_ids': [report_id], 'evidence_ids': snapshot['evidence_ids']})
        return SimpleNamespace(arun=run)
    monkeypatch.setitem(AGENT_REGISTRY, 'options_trading_analysis', build_report)
    rep_res = client.post('/api/options-platform/explain', json={'report_kind': 'scan',
        'report_id': report_id, 'message': 'Explain scan'})
    assert rep_res.status_code == 200, rep_res.text
    rep_body = rep_res.json()
    assert rep_body['agent_id'] == 'options_trading_analysis'
    assert rep_body['parent_run_id']
    assert rep_body['report_ids'] == [report_id]
    assert 'current_report' in report_captured[0]


def test_cross_user_conversation_rejected_before_mcp_fetch(client, app, monkeypatch):
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_risk', lambda config, snapshot, tools, *, scope:
        SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content={
            'answer': 'risk check', 'evidence_ids': [snapshot['evidence_id']],
            'risk_report_ids': [snapshot['risk_report']['report_id']]}))))
    first = client.post('/api/options-agent/portfolio/risk/chat', json={'message': 'risk'}).json()
    cid = first['conversation_id']
    assert client.post('/api/auth/register', json={'email': 'other-specialist@example.com',
        'password': 'test-password-123', 'display_name': 'Other'}).status_code == 200
    before = app.state.market.call.call_count
    cross = client.post('/api/options-agent/portfolio/risk/chat', json={'message': 'risk', 'conversation_id': cid})
    assert cross.status_code == 404
    assert app.state.market.call.call_count == before


def test_legacy_chain_conversation_rejected_on_continuation(client, app):
    # Seed legacy chain conversation without specialist metadata
    cid = str(uuid4())
    legacy_context = {'underlying': 'NIFTY', 'exchange': 'NSE', 'expiry': None}
    legacy_snap = {'snapshot_id': 'old-snap', 'rows': [], 'summary': {'put_call_ratio': None}}
    with app.state.store.connect() as db:
        db.execute('INSERT INTO option_chat_conversations VALUES (?,?,?,?)',
                   (cid, 1, json.dumps(legacy_context), '2026-01-01T00:00:00Z'))
        db.execute('INSERT INTO option_chat_turns(conversation_id,user_id,message,answer,evidence,created_at) VALUES (?,?,?,?,?,?)',
                   (cid, 1, 'old msg', 'old ans', json.dumps(legacy_snap), '2026-01-01T00:00:00Z'))
    # Readable via GET
    hist = client.get(f'/api/options-agent/conversations/{cid}')
    assert hist.status_code == 200
    assert hist.json()['context'] == legacy_context
    assert hist.json()['turns'][0]['snapshot'] == legacy_snap
    # Continuation through chat must fail with 409 conversation_scope_changed before MCP fetch
    before = app.state.market.call.call_count
    cont = client.post('/api/options-agent/chat', json={'message': 'continue', 'conversation_id': cid})
    assert cont.status_code == 409
    assert cont.json()['detail']['code'] == 'conversation_scope_changed'
    assert app.state.market.call.call_count == before


def test_history_bounded_context_and_trace_persistence(client, app, monkeypatch):
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_risk', lambda config, snapshot, tools, *, scope:
        SimpleNamespace(arun=AsyncMock(return_value=SimpleNamespace(content={
            'answer': 'risk check', 'evidence_ids': [snapshot['evidence_id']],
            'risk_report_ids': [snapshot['risk_report']['report_id']]}))))
    first = client.post('/api/options-agent/portfolio/risk/chat', json={'message': 'first'}).json()
    cid = first['conversation_id']
    with app.state.store.connect() as db:
        for i in range(5):
            db.execute('INSERT INTO option_chat_turns(conversation_id,user_id,message,answer,evidence,created_at) VALUES (?,?,?,?,?,?)',
                (cid, 1, f'msg-{i}', f'ans-{i}', json.dumps({'evidence_id': first['risk_snapshot']['evidence_id'], 'risk_report_id': first['risk_snapshot']['risk_report']['report_id']}), 'fixture'))
    prompts = []
    def capture(config, snapshot, tools, *, scope):
        async def run(prompt):
            prompts.append(json.loads(prompt))
            return SimpleNamespace(content={'answer': 'followup',
                'evidence_ids': [snapshot['evidence_id']],
                'risk_report_ids': [snapshot['risk_report']['report_id']]})
        return SimpleNamespace(arun=run)
    monkeypatch.setitem(AGENT_REGISTRY, 'portfolio_risk', capture)
    res = client.post('/api/options-agent/portfolio/risk/chat', json={'message': 'followup', 'conversation_id': cid})
    assert res.status_code == 200
    # Bounded to max 4 turns
    assert len(prompts[0]['previous_conversation']) <= 4
    # Trace persistence check
    run_rec = client.get('/api/options-agent/runs/' + res.json()['run_id']).json()
    detail = run_rec['detail']
    assert 'harness' in detail
    harness = detail['harness']
    assert 'attempts' in harness and 'tool_reads' in harness and 'stages' in harness
    # Ensure no leaked credentials or private account rows in trace
    assert 'password' not in str(harness) and 'secret' not in str(harness).lower() and 'holdings' not in str(harness)
