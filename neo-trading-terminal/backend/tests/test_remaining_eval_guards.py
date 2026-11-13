import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from app.terminal.analytics_runtime import TurnBudget


def test_live_flag_required(monkeypatch):
    from evals import remaining_live_evals
    monkeypatch.setattr("sys.argv", ["remaining_live_evals"])
    with pytest.raises(SystemExit) as exc:
        remaining_live_evals.main()
    assert exc.value.code == 2


def test_no_private_account_data_in_eval_output(tmp_path, monkeypatch):
    from evals import remaining_live_evals
    out_file = tmp_path / "eval_output.json"
    monkeypatch.setattr("sys.argv", ["remaining_live_evals", "--dry-run", "--output", str(out_file)])
    ret = remaining_live_evals.main()
    assert ret == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    # Verify no private tokens or secrets leaked
    forbidden = ["api_key", "secret", "private_token", "session-7", "broker_cookie"]
    for word in forbidden:
        assert word not in content.lower()
    data = json.loads(content)
    assert data.get("broker_evaluated") is False


def test_two_calls_include_prefetch():
    from evals.remaining_live_evals import enforce_turn_budget
    # At most 2 MCP calls per specialist turn including prefetch
    budget = TurnBudget()
    # Call 1 (prefetch): allowed
    assert enforce_turn_budget(budget, "options_trading_analysis") is True
    # Call 2: allowed
    assert enforce_turn_budget(budget, "options_trading_analysis") is True
    # Call 3: rejected!
    with pytest.raises(ValueError, match="MCP call limit exceeded: max 2 calls per turn"):
        enforce_turn_budget(budget, "options_trading_analysis")


def test_proposal_selection_no_third_call():
    from evals.remaining_live_evals import select_proposal_without_lookup
    # Candidate StrategyProposal IDs stay inside existing Options payloads; never add a lookup call
    proposals = [
        {"proposal_id": "11111111-1111-1111-1111-111111111111", "template": "bull_call_spread"},
        {"proposal_id": "22222222-2222-2222-2222-222222222222", "template": "bear_put_spread"},
    ]
    budget = TurnBudget()
    budget.consume("options_trading_analysis")  # call 1
    budget.consume("options_trading_analysis")  # call 2 (limit reached)

    # Selecting proposal must be pure in-memory lookup without adding MCP calls
    selected = select_proposal_without_lookup(proposals, "11111111-1111-1111-1111-111111111111", budget)
    assert selected["template"] == "bull_call_spread"
    assert budget.calls.get("options_trading_analysis", 0) == 2  # No new call added!


def test_continuation_rejects_changed_session():
    from evals.remaining_live_evals import validate_continuation_token
    now_ts = 1700000000.0
    token = {
        "continuation_id": "c-123",
        "session_generation": "session-gen-A",
        "created_at": now_ts,
        "resumption_count": 1,
    }
    # Matching session: valid
    assert validate_continuation_token(token, current_session="session-gen-A", now=now_ts + 60) is True

    # Changed session generation: invalid
    with pytest.raises(ValueError, match="Continuation invalidated on changed session"):
        validate_continuation_token(token, current_session="session-gen-B", now=now_ts + 60)

    # Expired token (> 10 minutes = 600s): invalid
    with pytest.raises(ValueError, match="Continuation expired"):
        validate_continuation_token(token, current_session="session-gen-A", now=now_ts + 601)

    # Exceeded max resumptions (> 2): invalid
    token_max = dict(token, resumption_count=3)
    with pytest.raises(ValueError, match="Continuation exceeded maximum resumptions"):
        validate_continuation_token(token_max, current_session="session-gen-A", now=now_ts + 60)
