import json
import asyncio
from types import SimpleNamespace


def test_offline_benchmark_uses_distinct_versioned_cases(capsys):
    from app.terminal.options_platform_evals import main

    assert main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "offline"
    assert report["model_quality"] == "unverified"
    assert {case["split"] for case in report["cases"]} == {"development", "heldout"}
    assert len({case["id"] for case in report["cases"]}) == len(report["cases"])
    assert {case["domain"] for case in report["cases"]} == {
        "strategy", "monitor", "scanner", "history", "private_mcp"
    }
    assert all(case["passed"] for case in report["cases"])
    by_id = {case["id"]: case for case in report["cases"]}
    strategy = by_id["call-entry"]
    assert strategy["evidence"]["report_id"] == strategy["evidence"]["report"]["report_id"]
    assert strategy["evidence"]["evidence_ids"] == strategy["evidence"]["report"]["evidence_ids"]
    assert strategy["engine_versions"]["calculation_version"] == strategy["evidence"]["report"]["calculation_version"]
    monitor = by_id["capital-deviation"]["evidence"]["report"]
    assert len(monitor["monitor_alerts_by_cycle"][0]) == len(monitor["monitor_alerts_by_cycle"][1]) == 2
    assert monitor["monitor_alerts_by_cycle"][0] == monitor["monitor_alerts_by_cycle"][1]
    assert by_id["filter-before-rank"]["engine_versions"]["ranking_policy"] == "exact-expiry-net-yield.1"
    assert by_id["physical-settlement"]["engine_versions"]["schema_version"] == "options-history.1"


def test_live_mode_requires_explicit_variant(capsys):
    from app.terminal.options_platform_evals import main
    import pytest

    with pytest.raises(SystemExit) as error:
        main(["--mode", "live-model"])
    assert error.value.code == 2
    assert "--variant" in capsys.readouterr().err


def test_live_mode_requires_free_access_confirmation(capsys):
    from app.terminal.options_platform_evals import main
    import pytest

    with pytest.raises(SystemExit) as error:
        main(["--mode", "live-model", "--variant", "tool"])
    assert error.value.code == 2
    assert "--confirm-free-access" in capsys.readouterr().err


def test_quota_error_stops_provider_calls_and_suppresses_details(monkeypatch):
    from agno.exceptions import ModelProviderError
    from app.core.config import Settings
    from app.terminal import options_platform_evals as evaluator

    calls = []

    async def quota(settings, variant, case):
        calls.append(case["id"])
        assert "expected" not in case
        raise ModelProviderError("private provider error", status_code=429)

    monkeypatch.setattr(evaluator, "run_model", quota)
    cases = [dict(id=str(i), passed=True, expected="answer key") for i in range(2)]
    asyncio.run(evaluator.model_comparison(cases, "base", Settings(_env_file=None),
                                           SimpleNamespace(configured=True)))
    assert calls == ["0"]
    assert all(case["model"]["failure"] == "provider_quota" for case in cases)
    assert all(case["model"]["cost"] is None for case in cases)
    assert "private provider error" not in json.dumps(cases)


def test_unconfigured_provider_never_attempts_model(monkeypatch):
    from app.terminal import options_platform_evals as evaluator

    async def unexpected_call(*args):
        raise AssertionError("Unconfigured provider cannot be called")

    monkeypatch.setattr(evaluator, "run_model", unexpected_call)
    cases = [dict(id="fixture", passed=True)]
    asyncio.run(evaluator.model_comparison(cases, "context", None, SimpleNamespace(configured=False)))
    result = cases[0]["model"]
    assert result["failure"] == "provider_not_configured"
    assert result["answer"] is None
    assert result["human_score"]["correctness"] is None
    assert "abstention" in result["human_score"]["evidence_availability_rule"].lower()


def test_context_and_tool_share_identical_bounded_evidence(monkeypatch):
    from agno import agent as agno_agent
    from app.core.config import Settings
    from app.terminal import options_model, options_platform_evals as evaluator
    from app.terminal.options_report_context import bounded_report

    sent = {}

    class ReplayAgent:
        def __init__(self, *, tools, **_):
            self.tools = tools

        async def arun(self, payload):
            prompt = json.loads(payload)
            if self.tools:
                result = await self.tools[0].session.call_tool("get_strategy_report", {})
                sent["tool"] = result.structured_content
            else:
                sent["context"] = prompt["evidence"]
            return SimpleNamespace(content="synthetic test")

    monkeypatch.setattr(agno_agent, "Agent", ReplayAgent)
    monkeypatch.setattr(options_model, "build_model", lambda _: object())
    evidence = {"report_kind": "strategy", "report_id": "real-report", "evidence_ids": ["real-evidence"],
                "report": {"report_id": "real-report", "evidence_ids": ["real-evidence"], "rows": ["x" * 250] * 200}}
    case = {"id": "large", "inputs": {}, "question": "What is supported?", "evidence": evidence}

    async def replay():
        for variant in ("context", "tool"):
            await evaluator.run_model(Settings(_env_file=None), variant, case)

    asyncio.run(replay())
    assert sent["context"] == sent["tool"] == bounded_report(evidence)
    assert sent["tool"]["report_id"] == "real-report"
    assert "report.rows" in sent["tool"]["omitted_counts"]
