import asyncio
import json
from app.terminal import options_evals


def test_risk_replay_versions_checks_and_sanitized_diagnostics(monkeypatch):
    def forbidden_model(*args, **kwargs):
        raise AssertionError("offline model call")
    monkeypatch.setattr(options_evals, "build_agent", forbidden_model)
    report = asyncio.run(options_evals.portfolio_risk_replay('offline'))
    assert report['total'] == report['passed'] == 11
    assert report['model_evaluated'] is False and report['cost'] is None
    for key in ('dataset_version', 'rubric_version', 'calculation_version', 'prompt_version', 'model_version'):
        assert key in report
    assert report['model_version'] is None
    assert report['explanation_rubric']['held_out'] is True
    assert report['explanation_rubric']['model_scored'] is False
    for case in report['results']:
        assert case['operational_failure'] is False
        assert case['checks']
        trace = case['diagnostics']
        assert set(trace) == {'report_id','evidence_id','policy_revision','calculation_version','enabled_count','assessed_count','duration_ms','outcome','failure_stage'}
        assert trace['failure_stage'] is None
        assert trace['duration_ms'] >= 0
        assert 'measured' not in json.dumps(trace)
    assert {c['id'] for c in report['results']} >= {'missing-value','zero-value','stale','disabled','adversarial-policy-order'}


def test_risk_diagnostics_failure_is_operational_and_sanitized():
    trace = options_evals.risk_diagnostics(None, 2.5, failure_stage='evaluation')
    assert trace['outcome'] == 'operational_failure'
    assert trace['failure_stage'] == 'evaluation'
    assert trace['report_id'] is None

def test_risk_offline_does_not_call_model(monkeypatch):
    monkeypatch.setattr(options_evals, 'build_agent', lambda *a, **k: (_ for _ in ()).throw(AssertionError('model called')))
    # Mode rejection happens before any network/model call.
    import pytest
    with pytest.raises(ValueError, match='offline only'):
        asyncio.run(options_evals.portfolio_risk_replay('live-model'))


def test_diagnostics_exclude_financial_provider_and_exception_fields():
    from types import SimpleNamespace
    from uuid import uuid4
    report = SimpleNamespace(report_id=uuid4(), evidence_id=uuid4(), policy_revision=4,
        calculation_version='portfolio-risk.1', summary='breach',
        coverage=SimpleNamespace(enabled=4, assessed=2),
        measured='987654321', provider_payload='SECRET_SENTINEL', credentials='TOKEN_SENTINEL')
    trace = options_evals.risk_diagnostics(report, 1)
    serialized = json.dumps(trace)
    assert trace['outcome'] == 'breach' and trace['failure_stage'] is None
    assert all(secret not in serialized for secret in ('987654321','SECRET_SENTINEL','TOKEN_SENTINEL','provider_payload','credentials'))

def test_diagnostics_failure_after_report_remains_operational():
    from types import SimpleNamespace
    from uuid import uuid4
    report = SimpleNamespace(report_id=uuid4(), evidence_id=uuid4(), policy_revision=4,
        calculation_version='portfolio-risk.1', summary='breach',
        coverage=SimpleNamespace(enabled=4, assessed=2))
    trace = options_evals.risk_diagnostics(report, 1.5, failure_stage='expectations')
    assert trace['outcome'] == 'operational_failure'
    assert trace['failure_stage'] == 'expectations'
    assert trace['report_id'] == str(report.report_id)
    assert trace['evidence_id'] == str(report.evidence_id)
    assert trace['policy_revision'] == 4


def test_replay_exercises_configured_missing_and_unsupported_inputs():
    result = asyncio.run(options_evals.portfolio_risk_replay('offline'))
    cases = {case['id']: case for case in result['results']}
    assert 'configured-missing-inputs' in cases
    assert 'configured-unsupported-basis' in cases
    for name in ('configured-missing-inputs', 'configured-unsupported-basis', 'unset'):
        assert cases[name]['passed']
        assert 'specific margin/loss abstention reasons' in cases[name]['checks']
