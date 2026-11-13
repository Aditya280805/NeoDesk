import asyncio
import json
import pytest

from app.terminal.analytics_evals import evaluate,fixtures,main


@pytest.mark.parametrize('dataset',['canonical','heldout'])
def test_offline_router_replay_reports_progress_without_claiming_model_quality(dataset):
    rows=[]
    report=asyncio.run(evaluate(on_result=rows.append,dataset=dataset))
    assert report['model_evaluated'] is False
    assert report['mode']=='offline-contract-replay'
    assert report['passed']==report['total']==len(fixtures(dataset))==len(rows)
    assert all(row['elapsed_seconds']>=0 for row in rows)
    assert 'provider' not in report


def test_cli_writes_sanitized_offline_report(tmp_path,monkeypatch,capsys):
    output=tmp_path/'router.json'
    monkeypatch.setattr('sys.argv',['analytics_evals','--output',str(output)])
    assert main()==0
    saved=json.loads(output.read_text(encoding='utf-8'))
    assert saved==json.loads(capsys.readouterr().out)
    assert not saved['model_evaluated']
    assert 'key' not in saved and 'question' not in saved['results'][0]


def test_specialist_live_smoke_requires_explicit_live_flag(monkeypatch):
    from unittest.mock import AsyncMock
    from evals import live_specialist_smoke
    call=AsyncMock()
    monkeypatch.setattr(live_specialist_smoke,'run',call)
    monkeypatch.setattr('sys.argv',['live_specialist_smoke'])
    with pytest.raises(SystemExit) as error:
        live_specialist_smoke.main()
    assert error.value.code==2
    call.assert_not_called()
