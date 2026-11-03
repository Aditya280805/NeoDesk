import asyncio
import json
import subprocess
import sys
from unittest.mock import patch

def test_portfolio_offline_evaluation_uses_real_mcp_and_reports_no_model():
    from app.terminal.options_evals import portfolio_replay
    with patch('app.terminal.options_evals.build_agent', side_effect=AssertionError('offline model call')):
        report = asyncio.run(portfolio_replay('offline'))
    assert report['scope'] == 'portfolio'
    assert report['dataset_version'] == 'portfolio-evals.v1'
    assert report['model_evaluated'] is False
    assert report['transport'] == 'streamable-http-mcp'
    assert report['cost'] is None
    assert report['passed'] == report['total'] >= 11
    assert all(r['checks'] and not r['failures'] for r in report['results'])

def test_portfolio_cli_and_explicit_chain_compatibility():
    for scope, total in [('chain', 6), ('portfolio', 11)]:
        run = subprocess.run([sys.executable, '-m', 'app.terminal.options_evals', '--scope', scope], capture_output=True, text=True, timeout=45)
        assert run.returncode == 0, run.stderr
        report = json.loads(run.stdout)
        assert report['passed'] == report['total'] == total
        assert report['model_evaluated'] is False

def test_portfolio_broker_smoke_cli_reports_truthful_metadata(monkeypatch, capsys):
    import httpx
    from app.terminal import options_evals
    requests = []
    def response(request):
        requests.append(request)
        return httpx.Response(200, json={'evidence_id':'synthetic-evidence'})
    client = httpx.AsyncClient
    monkeypatch.setenv('OPTIONS_SMOKE_TOKEN', 'synthetic-token')
    monkeypatch.setattr(options_evals.httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(response), **kwargs))
    monkeypatch.setattr(sys, 'argv', ['options_evals', '--scope', 'portfolio', '--mode', 'live-broker'])
    assert options_evals.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report['scope'] == 'portfolio'
    assert report['dataset_version'] is None
    assert report['rubric_version'] is None
    assert report['dataset_applicability'] == 'not_applicable; authenticated broker snapshot only'
    assert report['check_version'] == 'portfolio-broker-smoke.v1'
    assert report['model_evaluated'] is False
    assert report['cost'] is None
    check = report['results'][0]
    assert check['passed'] is True and check['failures'] == []
    assert check['checks'] == ['authenticated snapshot HTTP 200', 'evidence reference present']
    assert check['latency_ms'] >= 0 and check['usage'] is None
    assert requests[0].url.path == '/api/options-agent/portfolio/snapshot'
    assert json.loads(requests[0].content) == {}
