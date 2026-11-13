from datetime import date
import math
import pytest

from app.terminal.quant_risk import historical_tail, stress_matrix, historical_repricing


def _sample_option_position(cid="NIFTY26MAR24000CE", qty=50):
    return {
        "contract_id": cid,
        "underlying": "NIFTY",
        "kind": "option",
        "quantity": qty,
        "spot": 24000.0,
        "forward": 24050.0,
        "strike": 24000.0,
        "tau": 10 / 365.0,
        "iv": 0.15,
        "rate": 0.07,
        "option_type": "CALL",
    }


def test_tail_counts_249_250_999_1000_per_series_horizon():
    # Synthetic loss sequences
    def synthetic_losses(n):
        return [float(i) for i in range(1, n + 1)]

    # 1. Count = 249: Both 95% and 99% are unavailable
    res_249 = historical_tail(synthetic_losses(249))
    assert res_249["scenario_count"] == 249
    assert res_249["var_95"] is None
    assert res_249["cvar_95"] is None
    assert res_249["var_99"] is None
    assert res_249["cvar_99"] is None
    assert res_249["unavailable_reasons"]["var_95"] == "insufficient_history_for_95pct"
    assert res_249["unavailable_reasons"]["var_99"] == "insufficient_history_for_99pct"

    # 2. Count = 250: 95% is available, but 99% is unavailable
    res_250 = historical_tail(synthetic_losses(250))
    assert res_250["scenario_count"] == 250
    assert res_250["var_95"] is not None
    assert res_250["cvar_95"] is not None
    assert res_250["var_99"] is None
    assert res_250["cvar_99"] is None
    assert res_250["unavailable_reasons"]["var_99"] == "insufficient_history_for_99pct"
    assert "var_95" not in res_250["unavailable_reasons"]

    # 3. Count = 999: 95% is available, but 99% is unavailable
    res_999 = historical_tail(synthetic_losses(999))
    assert res_999["scenario_count"] == 999
    assert res_999["var_95"] is not None
    assert res_999["cvar_95"] is not None
    assert res_999["var_99"] is None
    assert res_999["cvar_99"] is None
    assert res_999["unavailable_reasons"]["var_99"] == "insufficient_history_for_99pct"

    # 4. Count = 1000: Both 95% and 99% are available
    res_1000 = historical_tail(synthetic_losses(1000))
    assert res_1000["scenario_count"] == 1000
    assert res_1000["var_95"] is not None
    assert res_1000["cvar_95"] is not None
    assert res_1000["var_99"] is not None
    assert res_1000["cvar_99"] is not None
    assert len(res_1000["unavailable_reasons"]) == 0


def test_95_available_when_99_missing():
    # Independent verification of tail quantile integration for 300 observations
    losses = [float(i) for i in range(1, 301)]
    res = historical_tail(losses)
    assert res["scenario_count"] == 300
    # 95% index = ceil(0.95 * 300) - 1 = 285 - 1 = 284 -> value is 285.0
    assert res["var_95"] == pytest.approx(285.0)
    # CVaR is the mean of worst 5% (top 15 values: 286..300)
    # sum(286..300) = (286 + 300) * 15 / 2 = 4395 -> mean = 4395 / 15 = 293.0
    assert res["cvar_95"] == pytest.approx(293.0)
    # 99% unavailable with exact reason
    assert res["var_99"] is None
    assert res["cvar_99"] is None
    assert res["unavailable_reasons"]["var_99"] == "insufficient_history_for_99pct"
    assert res["unavailable_reasons"]["cvar_99"] == "insufficient_history_for_99pct"


def test_stress_28_cells_independent_of_history():
    # Stress matrix evaluates 28 grid cells without requiring historical observations
    pos = [_sample_option_position()]
    stress = stress_matrix(pos, historical_losses=())
    assert len(stress["cells"]) == 28
    # 7 spot shocks: (-0.05, -0.03, -0.015, 0.0, 0.015, 0.03, 0.05)
    spot_shocks = {c["spot_shock"] for c in stress["cells"]}
    assert len(spot_shocks) == 7
    # 4 IV relative shocks: (-0.2, 0.0, 0.25, 0.5)
    iv_shocks = {c["iv_relative_shock"] for c in stress["cells"]}
    assert len(iv_shocks) == 4
    assert "worst_case_scenario" in stress
    assert "max_stress_loss" in stress
    assert stress["historical_tail"]["scenario_count"] == 0
    assert stress["risk_verdict"] == "CANNOT_ASSESS"


def test_nonfinite_and_duplicate_scenarios_rejected():
    # 1. Non-finite values in historical tail
    with pytest.raises(ValueError, match="Historical losses must be finite and validated"):
        historical_tail([1.0, 2.0, float("nan")])

    with pytest.raises(ValueError, match="Historical losses must be finite and validated"):
        historical_tail([1.0, 2.0, float("inf")])

    with pytest.raises(ValueError, match="Historical losses must be finite and validated"):
        historical_tail([1.0, 2.0, True])

    # 2. Duplicate contract positions in historical repricing
    pos_dup = [_sample_option_position(), _sample_option_position()]
    with pytest.raises(ValueError, match="Duplicate contract positions must be normalized"):
        historical_repricing(pos_dup, {})

    # 3. Non-consecutive or inverted historical sessions
    pos = [_sample_option_position()]
    bad_history = {
        "NIFTY26MAR24000CE": [
            {"date": "2026-03-01", "session": 1, "spot": 24000.0, "iv": 0.15},
            {"date": "2026-03-02", "session": 1, "spot": 24100.0, "iv": 0.15},  # duplicate session
        ]
    }
    with pytest.raises(ValueError, match="Historical observations must be ordered consecutive sessions"):
        historical_repricing(pos, bad_history)

    inverted_dates = {
        "NIFTY26MAR24000CE": [
            {"date": "2026-03-05", "session": 1, "spot": 24000.0, "iv": 0.15},
            {"date": "2026-03-02", "session": 2, "spot": 24100.0, "iv": 0.15},  # inverted date
        ]
    }
    with pytest.raises(ValueError, match="Historical observations must be ordered consecutive sessions"):
        historical_repricing(pos, inverted_dates)
