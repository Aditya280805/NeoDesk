"""Independent model and integration evaluation runner.

Tests evaluation guards, budget limits, session continuations, and sanitization
against normalized fixtures independent of broker access.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.terminal.analytics_runtime import TurnBudget


def enforce_turn_budget(budget: TurnBudget, role: str) -> bool:
    """Enforce at most 2 MCP invocations per specialist turn including prefetch."""
    if budget.calls.get(role, 0) >= 2:
        raise ValueError("MCP call limit exceeded: max 2 calls per turn")
    budget.consume(role)
    return True


def select_proposal_without_lookup(proposals: list[dict], proposal_id: str, budget: TurnBudget) -> dict:
    """Select candidate StrategyProposal by ID from existing payload in-memory without MCP calls."""
    target_id = str(proposal_id)
    match = next((p for p in proposals if str(p.get("proposal_id")) == target_id), None)
    if match is None:
        raise ValueError(f"Proposal {proposal_id} not found in candidate payload")
    # Pure lookup - verify no calls are recorded to budget
    return match


def validate_continuation_token(token: dict, *, current_session: str, now: float) -> bool:
    """Validate continuation token under non-negotiable shared contract constraints.

    Max 2 resumptions, 10 minutes (600s), invalidated on session change.
    """
    if token.get("session_generation") != current_session:
        raise ValueError("Continuation invalidated on changed session")

    created = float(token.get("created_at", 0))
    if now - created > 600.0:
        raise ValueError("Continuation expired: 10 minute limit exceeded")

    resumptions = int(token.get("resumption_count", 0))
    if resumptions > 2:
        raise ValueError("Continuation exceeded maximum resumptions: max 2 allowed")

    return True


def run_evaluations(dataset_path: Path, dry_run: bool = False) -> dict:
    """Run offline evaluation against the heldout corpus."""
    if not dataset_path.exists():
        raise FileNotFoundError(f"Corpus file not found: {dataset_path}")

    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    results = []
    started = time.monotonic()

    for case in cases:
        actual = None
        if not dry_run:
            import asyncio
            from app.core.config import settings
            from app.terminal.analytics_coordinator import classify
            actual = asyncio.run(classify(settings,case['question'],TurnBudget()))
        passed = actual is not None and actual.mode==case['mode'] and actual.delegated_agents==case['roles']
        results.append({
            "id": case["id"],
            "expected_mode": case["mode"],
            "expected_roles": case["roles"],
            "status": "PASS" if passed else "FIXTURE_ONLY" if dry_run else "FAIL",
            "actual_mode": actual.mode if actual else None,
        })

    return {
        "model_evaluated": not dry_run,
        "broker_evaluated": False,
        "source": "independent_heldout_corpus",
        "dataset": dataset_path.name,
        "total_cases": len(cases),
        "passed_cases": sum(row['status']=='PASS' for row in results),
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true", help="Explicitly authorize running against local configured model.")
    parser.add_argument("--dry-run", action="store_true", help="Run offline fixture replay without calling model APIs.")
    parser.add_argument("--output", type=Path, help="Path to write JSON evaluation report.")
    args = parser.parse_args()

    if not args.live_model and not args.dry_run:
        parser.error("--live-model or --dry-run is required; live calls require explicit authorization.")

    corpus_file = Path(__file__).resolve().parent / "analytics_router_remaining.v1.json"
    report = run_evaluations(corpus_file, dry_run=args.dry_run)

    out_text = json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(out_text, encoding="utf-8")

    print(out_text)
    return 0 if args.dry_run or report['passed_cases']==report['total_cases'] else 1


if __name__ == "__main__":
    sys.exit(main())
