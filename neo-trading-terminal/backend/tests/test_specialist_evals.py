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
        if schema is AgentAnswer:
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
