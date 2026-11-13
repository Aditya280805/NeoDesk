import asyncio
import json
from pathlib import Path
import subprocess
import sys
import pytest


def test_specialist_evals_offline_contract():
    from app.terminal.specialist_evals import specialist_replay

    report = asyncio.run(specialist_replay('offline'))
    assert report['mode'] == 'offline'
    assert report['model_evaluated'] is False
    assert report['model_version'] is None
    assert report['cost'] is None
    assert report['dataset_version'] == 'specialist-evals.v1'
    assert report['rubric_version'] == 'specialist-rubric.v1'
    assert 'automated_checks_limit' in report
    assert 'prompt_versions' in report
    assert 'tool_version' in report
    assert 'calculation_version' in report

    counts = report['sample_counts']
    assert counts['total'] == counts['passed'] > 0
    assert counts['failed'] == 0
    assert set(counts['by_split']) == {'development', 'held_out'}
    assert set(counts['by_scope']) == {'chain', 'portfolio', 'risk', 'clarify'}

    for cat in ('routing', 'numeric', 'citation', 'abstention'):
        summary = report['category_summaries'][cat]
        assert summary['passed'] == summary['total'] > 0

    agg = report['aggregate_metrics']
    assert 'calls' in agg
    assert 'total' in agg['calls']
    assert 'mcp_tool_reads' in agg['calls']
    assert agg['calls']['model_attempts'] == 0  # offline replay never invokes live models
    assert agg['calls']['schema_validations'] > 0
    assert 'latency_ms' in agg
    for metric in ('p50', 'p95', 'mean'):
        assert agg['latency_ms'][metric] >= 0

    # Routing is only scored on cases that genuinely execute routing
    assert 0 < report['category_summaries']['routing']['total'] < counts['total']

    assert len(report['results']) == counts['total']
    has_routed_case = False
    has_non_routed_case = False
    for r in report['results']:
        assert r['passed'] is True
        assert r['failures'] == []
        assert len(r['checks']) > 0
        assert 'actual_route' in r
        if r['actual_route'] is not None:
            has_routed_case = True
            assert r['actual_route'] == r['expected_route']
        else:
            has_non_routed_case = True
    assert has_routed_case and has_non_routed_case


def test_specialist_cases_and_rubric_file_integrity():
    evals_dir = Path(__file__).resolve().parents[1] / 'evals'
    cases_file = evals_dir / 'specialist_cases.json'
    rubric_file = evals_dir / 'specialist_rubric.json'

    assert cases_file.exists(), f"{cases_file} missing"
    assert rubric_file.exists(), f"{rubric_file} missing"

    cases_data = json.loads(cases_file.read_text(encoding='utf-8'))
    cases = cases_data['cases'] if isinstance(cases_data, dict) else cases_data
    scenarios = {c['scenario'] for c in cases}
    required_scenarios = {
        'normal', 'partial', 'stale', 'missing', 'injection',
        'forged_citation', 'scope_change', 'timeout', 'provider_failure',
    }
    assert required_scenarios.issubset(scenarios), f"Missing scenarios: {required_scenarios - scenarios}"

    splits = {c['split'] for c in cases}
    assert splits == {'development', 'held_out'}

    flows = {c['flow'] for c in cases}
    assert {'chain', 'portfolio', 'risk', 'clarify'}.issubset(flows)

    required_fields = {
        'id', 'split', 'scenario', 'flow', 'question',
        'expected_route', 'expected_tool', 'expected_citations',
        'numeric_expectations', 'forbidden_claims', 'forbidden_fields',
    }
    for c in cases:
        missing = required_fields - set(c.keys())
        assert not missing, f"Case {c.get('id')} missing fields: {missing}"

    rubric = json.loads(rubric_file.read_text(encoding='utf-8'))
    assert rubric.get('rubric_version') == 'specialist-rubric.v1'
    assert rubric.get('model_scored') is False
    assert 'dimensions' in rubric
    dims = rubric['dimensions']
    for expected_dim in ('routing', 'numeric', 'citation', 'abstention', 'scope_isolation', 'failure_handling'):
        assert expected_dim in dims


def test_specialist_evals_cli_offline():
    result = subprocess.run(
        [sys.executable, '-m', 'app.terminal.specialist_evals', '--mode', 'offline'],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI stderr: {result.stderr}\nstdout: {result.stdout}"
    report = json.loads(result.stdout)
    assert report['mode'] == 'offline'
    assert report['model_evaluated'] is False
    assert report['sample_counts']['passed'] == report['sample_counts']['total'] > 0


def test_live_model_requires_explicit_opt_in_and_validation():
    from app.terminal.specialist_evals import specialist_replay
    from app.core.config import Settings

    empty_config = Settings(_env_file=None, openai_api_key=None, gemini_api_key=None)
    with pytest.raises(ValueError, match='(required|configured|credentials)'):
        asyncio.run(specialist_replay('live-model', config=empty_config))


def test_live_model_mode_invokes_registered_agent_with_mock_transport(monkeypatch):
    import httpx
    from pydantic import SecretStr
    from app.terminal.specialist_evals import specialist_replay
    from app.core.config import Settings
    from app.terminal.agent_scope import RouteAnswer, AgentAnswer, PortfolioAnalysisAnswer, PortfolioRiskAnswer
    from agno.agent import Agent
    from agno.team import Team

    live_config = Settings(_env_file=None, openai_api_key=SecretStr('fixture-key'), options_agent_model='gpt-4.1-mini')

    model_calls = []

    # Mock agent and team arun
    original_arun_agent = Agent.arun
    original_arun_team = Team.arun

    async def mock_agent_arun(self, *args, **kwargs):
        model_calls.append(self.name)
        # return appropriate output based on output_schema
        schema = getattr(self, 'output_schema', None)
        if isinstance(schema,type) and issubclass(schema,AgentAnswer):
            return type('MockOutput', (), {'content': AgentAnswer(answer='Live chain analysis', snapshot_ids=['11111111-1111-1111-1111-111111111111']), 'metrics': None})()
        elif schema is PortfolioAnalysisAnswer:
            return type('MockOutput', (), {'content': PortfolioAnalysisAnswer(answer='Live portfolio analysis', evidence_ids=['22222222-2222-2222-2222-222222222222']), 'metrics': None})()
        elif schema is PortfolioRiskAnswer:
            return type('MockOutput', (), {'content': PortfolioRiskAnswer(answer='Live risk analysis', evidence_ids=['33333333-3333-3333-3333-333333333333'], risk_report_ids=['44444444-4444-4444-4444-444444444444']), 'metrics': None})()
        elif schema is RouteAnswer:
            return type('MockOutput', (), {'content': RouteAnswer(scope='chain'), 'metrics': None})()
        return type('MockOutput', (), {'content': {'answer': 'mock'}, 'metrics': None})()

    async def mock_team_arun(self, *args, **kwargs):
        model_calls.append(self.name)
        return type('MockOutput', (), {'content': RouteAnswer(scope='clarify'), 'metrics': None, 'status': None})()

    monkeypatch.setattr(Agent, 'arun', mock_agent_arun)
    monkeypatch.setattr(Team, 'arun', mock_team_arun)

    report = asyncio.run(specialist_replay('live-model', config=live_config))
    assert report['mode'] == 'live-model'
    assert report['model_evaluated'] is True
    assert report['model_version'] == 'gpt-4.1-mini'
    assert report['aggregate_metrics']['calls']['model_attempts'] > 0
    assert len(model_calls) > 0


def test_no_options_monitor_or_build_agent_imported_or_registered():
    from app.terminal.agent_registry import list_agents
    import app.terminal.options_agent as oa
    import app.terminal.options_evals as oe
    import app.terminal.specialist_evals as se

    assert 'options_monitor' not in list_agents()
    assert not hasattr(oa, 'build_agent')
    assert not hasattr(oe, 'build_agent')
    assert not hasattr(se, 'build_agent')


def test_frozen_fixtures_exist_and_match_envelope_schema():
    fixtures_dir = Path(__file__).resolve().parents[1] / 'evals' / 'fixtures' / 'specialist_api'
    assert fixtures_dir.is_dir(), f"Fixtures directory missing: {fixtures_dir}"

    expected_files = {
        'chain.json': {'scope': 'chain', 'status_code': 200, 'agent_id': 'options_trading_analysis', 'endpoint': '/api/options-agent/chat'},
        'portfolio.json': {'scope': 'portfolio', 'status_code': 200, 'agent_id': 'portfolio_analysis', 'endpoint': '/api/options-agent/portfolio/chat'},
        'risk.json': {'scope': 'risk', 'status_code': 200, 'agent_id': 'portfolio_risk', 'endpoint': '/api/options-agent/portfolio/risk/chat'},
        'clarify.json': {'scope': 'clarify', 'status_code': 200, 'agent_id': 'master_router', 'endpoint': '/api/options-agent/unified-chat'},
        'scope_change.json': {'scope': 'scope_change', 'status_code': 409, 'agent_id': None, 'endpoint': '/api/options-agent/unified-chat'},
    }

    for filename, expected in expected_files.items():
        file_path = fixtures_dir / filename
        assert file_path.exists(), f"Fixture missing: {filename}"
        data = json.loads(file_path.read_text(encoding='utf-8'))

        assert data.get('endpoint') == expected['endpoint'], f"{filename}: unexpected endpoint {data.get('endpoint')}"
        assert data.get('method') == 'POST', f"{filename}: method must be POST"
        assert data.get('status_code') == expected['status_code'], f"{filename}: unexpected status_code {data.get('status_code')}"
        assert data.get('scope') == expected['scope'], f"{filename}: unexpected scope {data.get('scope')}"
        assert data.get('agent_id') == expected['agent_id'], f"{filename}: unexpected agent_id {data.get('agent_id')}"
        assert isinstance(data.get('request'), dict), f"{filename}: request must be a dict"
        assert isinstance(data.get('response'), dict), f"{filename}: response must be a dict"


def test_frozen_fixtures_contract_validation():
    from app.terminal.options_snapshot import ChatRequest
    from app.terminal.agent_scope import (
        PortfolioChatRequest,
        AgentAnswer,
        PortfolioAnalysisAnswer,
        PortfolioRiskAnswer,
    )
    from app.terminal.unified_chat import UnifiedChatRequest
    from app.terminal.portfolio_contracts import PortfolioSnapshot
    from app.terminal.portfolio_risk_contracts import RiskReport

    fixtures_dir = Path(__file__).resolve().parents[1] / 'evals' / 'fixtures' / 'specialist_api'

    # 1. chain.json
    chain_f = json.loads((fixtures_dir / 'chain.json').read_text(encoding='utf-8'))
    req_chain = ChatRequest.model_validate(chain_f['request'])
    res_chain = chain_f['response']
    assert res_chain['agent_id'] == 'options_trading_analysis'
    assert res_chain['read_only'] is True
    assert isinstance(res_chain['snapshot_ids'], list) and len(res_chain['snapshot_ids']) == 1
    assert res_chain['snapshot']['snapshot_id'] == res_chain['snapshot_ids'][0]
    assert res_chain['snapshot']['underlying'] == req_chain.underlying
    assert 'parent_run_id' in res_chain and 'run_id' in res_chain
    assert 'conversation_id' in res_chain and 'created_at' in res_chain
    AgentAnswer(answer=res_chain['answer'], snapshot_ids=res_chain['snapshot_ids'])

    # 2. portfolio.json
    port_f = json.loads((fixtures_dir / 'portfolio.json').read_text(encoding='utf-8'))
    PortfolioChatRequest.model_validate(port_f['request'])
    res_port = port_f['response']
    assert res_port['agent_id'] == 'portfolio_analysis'
    assert res_port['read_only'] is True
    assert isinstance(res_port['evidence_ids'], list) and len(res_port['evidence_ids']) == 1
    assert str(res_port['evidence_ids'][0]) == str(res_port['portfolio_snapshot']['evidence_id'])
    assert 'parent_run_id' in res_port and 'run_id' in res_port
    assert 'conversation_id' in res_port and 'created_at' in res_port
    PortfolioSnapshot.model_validate(res_port['portfolio_snapshot'])
    PortfolioAnalysisAnswer(answer=res_port['answer'], evidence_ids=res_port['evidence_ids'])
    # Isolation: risk report/inputs must NOT be in portfolio response or snapshot
    assert 'risk_report' not in res_port['portfolio_snapshot']
    assert 'risk_inputs' not in res_port['portfolio_snapshot']
    assert 'risk_report_ids' not in res_port
    assert 'risk_snapshot' not in res_port

    # 3. risk.json
    risk_f = json.loads((fixtures_dir / 'risk.json').read_text(encoding='utf-8'))
    PortfolioChatRequest.model_validate(risk_f['request'])
    res_risk = risk_f['response']
    assert res_risk['agent_id'] == 'portfolio_risk'
    assert res_risk['read_only'] is True
    assert isinstance(res_risk['evidence_ids'], list) and len(res_risk['evidence_ids']) == 1
    assert isinstance(res_risk['risk_report_ids'], list) and len(res_risk['risk_report_ids']) == 1
    assert str(res_risk['evidence_ids'][0]) == str(res_risk['risk_snapshot']['evidence_id'])
    assert str(res_risk['risk_report_ids'][0]) == str(res_risk['risk_snapshot']['risk_report']['report_id'])
    assert 'parent_run_id' in res_risk and 'run_id' in res_risk
    assert 'conversation_id' in res_risk and 'created_at' in res_risk
    RiskReport.model_validate(res_risk['risk_snapshot']['risk_report'])
    PortfolioRiskAnswer(
        answer=res_risk['answer'],
        evidence_ids=res_risk['evidence_ids'],
        risk_report_ids=res_risk['risk_report_ids'],
    )
    # Isolation: no holdings, positions, funds, orders rows in risk snapshot
    assert 'portfolio_snapshot' not in res_risk
    assert 'sections' not in res_risk['risk_snapshot']
    for forbidden_section in ('holdings', 'positions', 'funds', 'orders'):
        assert forbidden_section not in res_risk['risk_snapshot']
        assert forbidden_section not in res_risk['risk_snapshot']['risk_report']

    # 4. clarify.json
    clarify_f = json.loads((fixtures_dir / 'clarify.json').read_text(encoding='utf-8'))
    UnifiedChatRequest.model_validate(clarify_f['request'])
    res_clarify = clarify_f['response']
    assert res_clarify['scope'] == 'clarify'
    assert res_clarify['agent_id'] == 'master_router'
    assert res_clarify['read_only'] is True
    assert res_clarify['conversation_id'] is None
    assert 'run_id' in res_clarify and 'parent_run_id' in res_clarify
    assert isinstance(res_clarify['answer'], str) and len(res_clarify['answer'].strip()) > 0
    # Zero evidence fields in clarify response
    for ev_field in ('snapshot', 'portfolio_snapshot', 'risk_snapshot', 'report', 'evidence_ids', 'snapshot_ids', 'risk_report_ids'):
        assert ev_field not in res_clarify

    # 5. scope_change.json
    scope_change_f = json.loads((fixtures_dir / 'scope_change.json').read_text(encoding='utf-8'))
    req_sc = UnifiedChatRequest.model_validate(scope_change_f['request'])
    assert req_sc.conversation_id is not None
    assert scope_change_f['status_code'] == 409
    res_sc = scope_change_f['response']
    assert 'detail' in res_sc
    assert res_sc['detail'].get('code') == 'conversation_scope_changed'
    assert isinstance(res_sc['detail'].get('message'), str) and len(res_sc['detail']['message']) > 0


def test_frozen_fixtures_and_handoff_sentinel_and_secret_scan():
    backend_dir = Path(__file__).resolve().parents[1]
    fixtures_dir = backend_dir / 'evals' / 'fixtures' / 'specialist_api'
    handoff_file = backend_dir.parent / 'docs' / 'superpowers' / 'plans' / 'SPECIALIST_AGENTS_HANDOFF.md'

    assert fixtures_dir.is_dir(), f"Fixtures directory missing: {fixtures_dir}"

    forbidden_patterns = [
        'Bearer ',
        'SECRET_SENTINEL',
        'session_generation',
        'capability',
        'test-key',
        'sk-',
        'AIza',
    ]

    for p in fixtures_dir.glob('*.json'):
        text = p.read_text(encoding='utf-8')
        for pat in forbidden_patterns:
            assert pat not in text, f"Forbidden pattern '{pat}' found in fixture {p.name}"

    assert handoff_file.is_file(), f"Handoff doc missing: {handoff_file}"
    text = handoff_file.read_text(encoding='utf-8')
    for pat in ['SECRET_SENTINEL', 'test-key', 'Bearer ey', 'sk-', 'AIza', 'PRIVATE KEY']:
        assert pat not in text, f"Forbidden pattern '{pat}' found in handoff doc"

