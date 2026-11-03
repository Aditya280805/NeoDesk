"""Versioned synthetic options-platform benchmark with an opt-in model experiment."""

import argparse
import asyncio
from contextlib import contextmanager
import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException

from .options_backtest import run_backtest
from .options_backtest_jobs import BacktestService
from .options_history import parse_history
from .options_history_contracts import BacktestRequest, ImportDeclaration
from .options_market_contracts import MarketContract, MarketQuote, StrategyMarketEvidence
from .options_mcp import TOOL_VERSION, OptionsMCP
from .options_platform_risk import EquityObservation, MonitoringSettings, PlatformRiskPolicy, evaluate_platform_risk
from .options_platform_store import OptionsPlatformStore
from .options_report_context import bounded_report, load_report
from .options_scan_jobs import ScanJobStore
from .options_scanner import ScanCriteria, scan_evidence
from .options_strategies import analyze_strategy
from .options_strategy_contracts import HoldingEvidence, StrategyRequest
from .portfolio_contracts import PortfolioSnapshot

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 1, 1, tzinfo=UTC)
COSTS = dict(opening_fees_inr="6", expiry_fees_inr="0", stock_slippage_per_unit="0",
             call_slippage_per_unit="0", put_slippage_per_unit="0")
VARIANTS = ("base", "prompt", "context", "tool")


def fixture_id(label):
    return uuid5(NAMESPACE_URL, f"options-platform-evals.1/{label}")


def number(value):
    return None if value is None else format(Decimal(value).normalize(), "f")


def envelope(kind, report, evidence_ids):
    return dict(report_kind=kind, report_id=report["report_id"], evidence_ids=evidence_ids,
                report=report, observation_notice="Synthetic historical fixture. No live market claim.")


def market():
    rows = [("stock", "equity", None, "100"), ("call-a", "call", "110", "5"),
            ("call-b", "call", "115", "6"), ("put", "put", "90", "2")]
    contracts = tuple(
        MarketContract(instrument_id=id, underlying_id="stock", kind=kind, strike=strike,
                       expiry=None if kind == "equity" else (NOW + timedelta(days=30)).date(),
                       lot_size=10, identity_verified=True, settlement_verified=True,
                       settlement_rule_version="fixture-rule-001", basis="synthetic",
                       provenance=("synthetic fixture settlement rule; not exchange certification",))
        for id, kind, strike, _ in rows
    )
    quotes = tuple(
        MarketQuote(contract_id=id, observed_at=NOW, exchange_timestamp=NOW, bid=price, ask=price,
                    bid_quantity=10, ask_quantity=10, volume=50, open_interest=100,
                    source="fixture", provenance=("evaluation fixture",))
        for id, _, _, price in rows
    )
    return StrategyMarketEvidence(evidence_id=fixture_id("market"), observed_at=NOW, contracts=contracts, quotes=quotes,
                                  source="fixture", completeness="complete")


def strategy(inputs, evidence):
    kind = inputs["kind"]
    owned = inputs.get("owned", False)
    req = StrategyRequest(kind=kind, mode="owned" if owned else "hypothetical", stock_contract_id="stock",
                          call_contract_id="call-a", put_contract_id="put" if kind == "collar" else None,
                          quantity=inputs["quantity"], evidence_id=evidence.evidence_id,
                          holding_row_id="holding" if owned else None, quote_max_age_seconds=60, costs=COSTS)
    holdings = (HoldingEvidence(row_id="holding", stock_contract_id="stock", underlying_id="stock",
                                available_quantity=10, acquisition_cost_per_share=90, observed_at=NOW,
                                evidence_id=evidence.evidence_id, identity_verified=True, coverage_verified=True),) if owned else ()
    report = analyze_strategy(req, evidence, holdings, NOW)
    return report.model_copy(update={"report_id": fixture_id(f"strategy/{kind}/{req.quantity}/{req.mode}")})


class EvalDatabase:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()


def monitor(inputs, store, report):
    equity = tuple(
        EquityObservation(observed_at=NOW - timedelta(minutes=2 - i), sequence=i,
                          equity_inr=value, external_flow_inr=flow)
        for i, (value, flow) in enumerate(((100, 0), (200, 100), (180, 0)))
    )
    snapshot = PortfolioSnapshot(evidence_id=fixture_id("portfolio"), retrieval_started_at=NOW,
                                 retrieval_finished_at=NOW, source_observed_at=NOW)
    associations = (dict(baseline_analysis_id=report.report_id, executed_confirmed=True,
                         current_coverage_verified=inputs["coverage"]),)
    risk = evaluate_platform_risk(PlatformRiskPolicy(capital_cap_inr=900, drawdown_maxpercent=5),
                                  snapshot, (report,), associations, equity, as_of=NOW)
    checks = {row["key"]: row for row in risk["checks"]}
    outcomes = {key: row["outcome"] for key, row in checks.items()}
    store.put_monitoring(7, MonitoringSettings(enabled=True), now=0)
    expiry_spot = Decimal(120)
    comparison = (report.acquisition_basis.profit_at(expiry_spot)
                  - report.current_basis.profit_at(expiry_spot))
    risk["basis_comparison"] = dict(expiry_spot=str(expiry_spot),
                                    acquisition_minus_current_payoff=number(comparison),
                                    scope="theoretical payoff basis comparison, not realized P&L")
    alert_history = []
    for instant in (0, 61):
        claim = store.claim_monitor(7, "synthetic-generation", now=instant)
        cycle_report = dict(risk, report_id=str(fixture_id(f"risk/{inputs['coverage']}/{instant}")))
        if not store.finish_monitor(7, claim, outcomes, now=instant + 1, report=cycle_report):
            raise RuntimeError("Evaluation monitor did not publish")
        alert_history.append(store.list_alerts(7))
    alerts = alert_history[-1]
    selected = load_report(store.store, 7, "alert", alerts[0]["id"])
    selected["report"]["monitor_alerts_by_cycle"] = alert_history
    return dict(capital=outcomes["capital"], drawdown=number(checks["drawdown"]["value"]),
                breaches=sum(state == "breach" for state in outcomes.values()),
                repeat_alerts=len(alerts), basis_deviation=number(comparison)), selected


def scanner(inputs, evidence, store):
    criteria = ScanCriteria(capital_inr=2000, strategy="covered_call", scope="hypothetical",
                            min_expiry_days=1, max_expiry_days=60, minimum_volume=0,
                            minimum_open_interest=0, minimum_depth=inputs["depth"],
                            maximum_relative_spread="0.1", maximum_loss_inr=2000,
                            quote_max_age_seconds=60, costs=COSTS)
    result = scan_evidence(criteria, evidence, (), NOW, combination_limit=inputs["limit"])
    for row in result["candidates"]:
        row["report"]["report_id"] = str(fixture_id(f"scan/{row['contracts'][1]}"))
    store.save_market_evidence(7, evidence)
    scans = ScanJobStore(store)
    scans.create(7, criteria, dict(status="complete", total_contracts=2, underlyings=["stock"]), now=100)
    job, token = scans.claim(now=100)
    job.update({key: result[key] for key in ("candidates", "exclusions", "visited_combinations",
                                            "total_combinations", "missing_combinations")})
    job.update(status="partial" if result["partial"] else "completed", cursor=1,
               contracts_visited=2, evidence_ids=[str(evidence.evidence_id)])
    if not scans.publish(job, token, terminal=True):
        raise RuntimeError("Evaluation scan did not publish")
    selected = load_report(store.store, 7, "scan", job["id"])
    return dict(ranked_calls=[row["contracts"][1] for row in result["candidates"]],
                partial=result["partial"], visited=result["visited_combinations"],
                excluded=[row["reason"] for row in result["exclusions"]]), selected


def history_dataset(inputs):
    examples = ROOT / "examples" / "options-history"
    with (examples / "synthetic-collar.csv").open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fields = reader.fieldnames
    request = BacktestRequest.model_validate_json((examples / "backtest-request.json").read_text())
    first, fill, expiry = request.valuation_times
    if inputs["mutation"] == "late_fill":
        for row in rows:
            if row["record_id"] == "q-C-1":
                row["known_at"] = expiry.isoformat()
    elif inputs["mutation"] == "missing_quote":
        rows = [row for row in rows if row["record_id"] != "q-C-1"]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    declaration = ImportDeclaration(
        provenance="Shipped synthetic collar example", licence="Own synthetic data", dataset_status="synthetic",
        expected_intervals=[dict(contract_id=id, start=first, end=fill, interval_seconds=60)
                            for id in ("S", "C", "P")],
    )
    return parse_history(stream.getvalue().encode(), "csv", declaration), request


def history(inputs):
    dataset, request = history_dataset(inputs)
    gaps = len(dataset["coverage"]["gaps"])
    try:
        report = run_backtest(dataset, request)
    except ValueError as exc:
        if str(exc) != "unsupported_period_quote_gap":
            raise
        report = dict(cash=None, net_profit=None, status="unsupported_period_quote_gap")
    filled = sum(trade["quantity"] for trade in report.get("trades", ()))
    report.update(report_id=str(fixture_id(f"history/{inputs['mutation']}")),
                  schema_version=dataset["schema_version"], dataset_hash=dataset["content_hash"],
                  coverage=dataset["coverage"])
    return (dict(cash=report["cash"], net_profit=report["net_profit"], gaps=gaps, filled=filled),
            envelope("backtest", report, [report["dataset_hash"]]))


async def private_mcp(inputs, store, evidence):
    scope = inputs["scope"]
    if scope == "strategy":
        report = strategy(dict(kind="covered_call", quantity=10), evidence)
        store.save_market_evidence(7, evidence)
        store.save_report(7, "analysis", report)
        report_id = report.report_id
    else:
        service = BacktestService(store, clock=lambda: 100)
        dataset, request = history_dataset({"mutation": "none"})
        manifest = service.history.save(7, dataset)
        job = service.create(7, request.model_copy(update={"dataset_id": UUID(manifest["id"])}))
        report_id = job["id"]
        for _ in range(job["event_count"] + 1):
            if not service.tick_sync():
                break
    selected = load_report(store.store, 7, scope, report_id)
    owner_denied = False
    try:
        load_report(store.store, 8, scope, report_id)
    except HTTPException as error:
        owner_denied = error.status_code == 404
    runtime = OptionsMCP(None, port=0)
    async with runtime.lifespan():
        async with runtime.connection(7, None, "eval", scope=scope, selected_report=selected) as connection:
            name = f"get_{scope}_report"
            response = await connection._snapshot(name)
            foreign = await connection.tools.session.call_tool(name, {"report_id": "foreign"}, raise_on_error=False)
            owner = await connection.tools.session.call_tool(name, {"user_id": 8}, raise_on_error=False)
            market_read = await connection.tools.session.call_tool("get_option_snapshot", {}, raise_on_error=False)
            actual = dict(tools=list(connection.tools.functions), exact_reference=response == selected,
                          cross_owner_denied=owner.is_error and owner_denied,
                          foreign_selection_denied=foreign.is_error, market_denied=market_read.is_error)
    return actual, response


async def evaluate_case(case, store):
    domain, inputs = case["domain"], case["inputs"]
    evidence = market()
    if domain == "strategy":
        report = strategy(inputs, evidence)
        payoff = report.current_basis.profit_at(Decimal(inputs.get("spot", "120"))) if report.current_basis else None
        serialized = report.model_dump(mode="json")
        return dict(status=report.status, payoff=number(payoff), capital=number(report.current_capital),
                    cost=number(report.costs.total_inr) if report.costs else None,
                    margin=number(report.broker_margin)), envelope("strategy", serialized, serialized["evidence_ids"])
    if domain == "monitor":
        return monitor(inputs, store, strategy(dict(kind="covered_call", quantity=10, owned=True), evidence))
    if domain == "scanner":
        return scanner(inputs, evidence, store)
    if domain == "history":
        return history(inputs)
    if domain == "private_mcp":
        return await private_mcp(inputs, store, evidence)
    raise ValueError("Unknown evaluation domain")


def engine_versions(selected):
    report = selected["report"]
    if selected["report_kind"] == "alert":
        report = report["linked_evidence"]["risk_report"]
    versions = {key: report[key] for key in ("version", "calculation_version", "ranking_policy", "schema_version")
                if key in report}
    if "cost_assumptions" in report:
        versions["cost_assumptions_version"] = report["cost_assumptions"]["version"]
    return versions


async def benchmark():
    cases = json.loads((ROOT / "evals" / "options_platform_cases.json").read_text(encoding="utf-8"))
    results = []
    with TemporaryDirectory(prefix="options-platform-eval-") as scratch:
        for case in cases:
            started = perf_counter()
            versions = {}
            try:
                store = OptionsPlatformStore(EvalDatabase(Path(scratch) / f"{case['id']}.sqlite3"))
                actual, evidence = await evaluate_case(case, store)
                failure = None if actual == case["expected"] else "deterministic_mismatch"
                versions = engine_versions(evidence)
                evidence = bounded_report(evidence)
            except Exception as error:
                actual, evidence, failure = None, None, type(error).__name__
            results.append(dict(case, actual=actual, evidence=evidence, passed=failure is None,
                                engine_versions=versions, failure=failure,
                                latency_ms=round((perf_counter() - started) * 1000, 2)))
    return results


async def run_model(settings, variant, case):
    """Use a single provider, with no backup, retries, or application credentials in input."""
    from agno.agent import Agent
    from .options_model import build_model, close_agent_model, options_run

    instructions = []
    if variant != "base":
        instructions = ["Interpret only supplied synthetic evidence. Never invent financial values, live verification, "
                        "permissions or reference IDs. State what is unavailable and cite exact evidence/report IDs."]
    payload = {"question": case["question"], "inputs": case["inputs"]}
    selected = bounded_report(case["evidence"]) if variant in {"context", "tool"} else None
    if variant == "context":
        payload["evidence"] = selected
    config = settings.model_copy(update={"gemini_backup_api_key": None, "openai_backup_api_key": None})
    runtime = OptionsMCP(None, port=0) if variant == "tool" else None
    token = options_run.set(True)

    async def invoke(tools):
        agent = Agent(model=build_model(config), instructions=instructions, tools=tools, tool_call_limit=2,
                      telemetry=False, markdown=False)
        try:
            output = await agent.arun(json.dumps(payload))
        finally:
            await close_agent_model(agent)
        metrics = getattr(output, "metrics", None)
        usage = {key: getattr(metrics, key, None) for key in ("input_tokens", "output_tokens", "total_tokens")}
        if not isinstance(output.content, str) or not output.content.strip():
            raise ValueError("Empty model response")
        return output.content, usage

    try:
        async with asyncio.timeout(60):
            if runtime is None:
                return await invoke([])
            async with runtime.lifespan():
                async with runtime.connection(7, None, "model-eval", scope=selected["report_kind"],
                                              selected_report=selected) as connection:
                    return await invoke([connection.tools])
    finally:
        options_run.reset(token)


async def model_comparison(cases, variant, settings, provider):
    from .options_model import provider_failure

    stop_reason = None if provider.configured else "provider_not_configured"
    evidence_rule = ("Only question and case parameters are provided. Score grounded abstention positively "
                     "for missing values and references; never require hidden evidence."
                     if variant in {"base", "prompt"} else
                     "Score using the bounded evidence available to this arm. Credit abstention for omitted "
                     "or unavailable values; require exact references and supported claims when evidence is present.")
    for case in cases:
        started = perf_counter()
        answer, usage, failure = None, None, stop_reason
        if failure is None and not case["passed"]:
            failure = "offline_case_failed"
        if failure is None:
            try:
                model_input = {key: case[key] for key in ("id", "question", "inputs", "evidence") if key in case}
                answer, usage = await run_model(settings, variant, model_input)
            except TimeoutError:
                failure = "timeout"
            except Exception as error:
                failure, _ = provider_failure(settings, error)
                if failure in {"provider_quota", "provider_auth", "provider_permission", "provider_model"}:
                    stop_reason = failure
        case["model"] = dict(answer=answer, usage=usage, failure=failure, cost=None,
                             latency_ms=round((perf_counter() - started) * 1000, 2),
                             human_score=dict(correctness=None, exact_references=None, abstention=None,
                                              critical_fabrication=None, unauthorized_claim=None, notes=None,
                                              evidence_availability_rule=evidence_rule))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live-model"), default="offline")
    parser.add_argument("--variant", choices=VARIANTS)
    parser.add_argument("--confirm-free-access", action="store_true",
                        help="Confirm independently that the configured project/model has free access.")
    args = parser.parse_args(argv)
    if args.mode == "live-model" and not args.variant:
        parser.error("--mode live-model requires --variant")
    if args.mode == "live-model" and not args.confirm_free_access:
        parser.error("--mode live-model requires --confirm-free-access")
    if args.mode == "offline" and (args.variant or args.confirm_free_access):
        parser.error("--variant and --confirm-free-access apply only to live-model")

    async def run():
        cases = await benchmark()
        provider = None
        if args.mode == "live-model":
            from app.core.config import Settings
            from .options_model import provider_settings

            settings = Settings()
            provider = provider_settings(settings)
            await model_comparison(cases, args.variant, settings, provider)
        return cases, provider

    cases, provider = asyncio.run(run())
    report = dict(mode=args.mode, variant=args.variant, provider=provider.provider if provider else None,
                  model=provider.model if provider else None, dataset_version="options-platform-evals.1",
                  prompt_version="options-platform-experiment.1", rubric_version="options-platform-rubric.1",
                  tool_version=TOOL_VERSION, cost=None, implementation_status="implemented",
                  offline_status="passed" if all(case["passed"] for case in cases) else "failed",
                  model_quality="unverified", live_broker="unverified", deployment="unverified",
                  promotion_criteria=["all deterministic and authorization cases pass",
                                      "zero critical fabrications or unauthorized claims",
                                      "all exact references present", "no scored heldout regression"],
                  cases=cases)
    print(json.dumps(report, indent=2))
    return int(any(not case["passed"] or case.get("model", {}).get("failure") for case in cases))


if __name__ == "__main__":
    raise SystemExit(main())
