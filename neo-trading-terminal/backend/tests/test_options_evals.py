import json
import subprocess
import sys


def test_offline_eval_replays_mcp_without_claiming_model_quality():
    result = subprocess.run([sys.executable, '-m', 'app.terminal.options_evals'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['scope'] == 'chain'
    assert report['cost'] is None
    assert report['mode'] == 'offline'
    assert report['model_evaluated'] is False
    assert report['passed'] == report['total'] == 6


def test_live_broker_check_requires_explicit_session_token(monkeypatch):
    monkeypatch.delenv('OPTIONS_SMOKE_TOKEN', raising=False)
    result = subprocess.run([sys.executable, '-m', 'app.terminal.options_evals', '--mode', 'live-broker'],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert 'OPTIONS_SMOKE_TOKEN' in result.stderr

def test_portfolio_risk_cli_is_explicit_offline_and_versioned():
    result = subprocess.run([sys.executable, '-m', 'app.terminal.options_evals', '--scope', 'portfolio-risk'],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['scope'] == 'portfolio-risk'
    assert report['total'] == report['passed'] == 11
    assert report['model_evaluated'] is False and report['cost'] is None
    assert report['prompt_version'] == 'portfolio.2'
    assert report['explanation_rubric']['model_scored'] is False
