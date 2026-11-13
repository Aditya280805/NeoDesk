from datetime import date
import pytest

from app.terminal.quant_compliance import (
    compliance_checks,
    declared_compliance_checks,
    expiry_rule_applicability,
    aggregate_underlying_compliance,
)


def test_index_not_subject_to_stock_ban():
    positions = [
        {"contract_id": "NIFTY26MAR24000CE", "quantity": 50, "lot_size": 50, "underlying": "NIFTY"}
    ]
    # Even if someone attempts to pass ban_active=True with scope index_derivative:
    rules = {
        "declared_records": [
            {
                "contract_id": "NIFTY26MAR24000CE",
                "source": "NSE",
                "revision": "v1",
                "instrument_scope": "index_derivative",
                "valid_from": date(2026, 3, 1),
                "valid_until": date(2026, 3, 31),
                "lot_size": 50,
                "ban_active": True,
                "base_futeq": 50,
                "current_futeq": 100,
            }
        ]
    }
    result = compliance_checks(positions, rules)
    mwpl_findings = [f for f in result["findings"] if f["code"] == "mwpl"]
    assert len(mwpl_findings) > 0
    # Must NOT breach: index derivatives are exempt from stock MWPL ban
    assert not any(f["outcome"] == "breach" for f in mwpl_findings)
    assert any(f["reason"] == "stock_mwpl_rule_not_applicable_or_scope_unverified" for f in mwpl_findings)
    assert result["risk_verdict"] == "CANNOT_ASSESS"


def test_same_underlying_multiple_contracts_aggregate():
    # An account holds two contracts on TATASTEEL (a stock derivative)
    positions = [
        {"contract_id": "TATASTEEL26MARFUT", "underlying": "TATASTEEL", "quantity": 550, "lot_size": 550},
        {"contract_id": "TATASTEEL26MAR150CE", "underlying": "TATASTEEL", "quantity": 1100, "lot_size": 550},
    ]
    # Contract 1 reduced FutEq (+550 -> +200), Contract 2 increased FutEq (+300 -> +400)
    # Aggregate base = 550 + 300 = 850; aggregate current = 200 + 400 = 600 (net reduction)
    records = [
        {
            "contract_id": "TATASTEEL26MARFUT",
            "underlying": "TATASTEEL",
            "source": "NSE",
            "revision": "v1",
            "instrument_scope": "stock_derivative",
            "valid_from": date(2026, 3, 1),
            "valid_until": date(2026, 3, 31),
            "lot_size": 550,
            "ban_active": True,
            "base_futeq": 550,
            "current_futeq": 200,
        },
        {
            "contract_id": "TATASTEEL26MAR150CE",
            "underlying": "TATASTEEL",
            "source": "NSE",
            "revision": "v1",
            "instrument_scope": "stock_derivative",
            "valid_from": date(2026, 3, 1),
            "valid_until": date(2026, 3, 31),
            "lot_size": 550,
            "ban_active": True,
            "base_futeq": 300,
            "current_futeq": 400,
        },
    ]
    agg = aggregate_underlying_compliance(positions, records)
    assert "TATASTEEL" in agg["underlying_summaries"]
    tata = agg["underlying_summaries"]["TATASTEEL"]
    assert tata["aggregate_base_futeq"] == 850
    assert tata["aggregate_current_futeq"] == 600
    assert tata["aggregate_exposure_increased"] is False
    assert tata["aggregate_sign_reversed"] is False
    # If another contract made aggregate current 1000 (> 850):
    records_increase = [dict(r) for r in records]
    records_increase[1]["current_futeq"] = 800  # total = 1000 > 850
    agg_inc = aggregate_underlying_compliance(positions, records_increase)
    assert agg_inc["underlying_summaries"]["TATASTEEL"]["aggregate_exposure_increased"] is True
    assert any(f["outcome"] == "breach" and f["code"] == "aggregate_underlying_mwpl" for f in agg_inc["findings"])


def test_sign_reversal_and_intraday_increase():
    # Case 1: Sign reversal (+100 -> -50)
    pos = [{"contract_id": "STOCKFUT", "quantity": 100}]
    rec_reversal = [
        {
            "contract_id": "STOCKFUT",
            "source": "NSE",
            "revision": "v1",
            "instrument_scope": "stock_derivative",
            "valid_from": date(2026, 3, 1),
            "valid_until": date(2026, 3, 31),
            "lot_size": 100,
            "ban_active": True,
            "base_futeq": 100,
            "current_futeq": -50,
        }
    ]
    res_reversal = declared_compliance_checks(pos, rec_reversal)
    assert any(f["outcome"] == "breach" and f["reason"] == "ban_delta_sign_reversal" for f in res_reversal["findings"])
    assert res_reversal["scenario_verdict"] == "DECLARED_BREACH"

    # Case 2: Intraday increase (+100 -> +150)
    rec_increase = [dict(rec_reversal[0], current_futeq=150)]
    res_increase = declared_compliance_checks(pos, rec_increase)
    assert any(f["outcome"] == "breach" and f["reason"] == "ban_declared_exposure_increase" for f in res_increase["findings"])
    assert res_increase["scenario_verdict"] == "DECLARED_BREACH"

    # Case 3: Reduction without verified account coverage (+100 -> +80)
    rec_reduction = [dict(rec_reversal[0], current_futeq=80)]
    res_reduction = declared_compliance_checks(pos, rec_reduction)
    assert not any(f["outcome"] == "breach" for f in res_reduction["findings"])
    assert any(f["reason"] == "reduction_declared_but_account_and_intraday_coverage_unverified" for f in res_reduction["findings"])
    assert res_reduction["scenario_verdict"] == "INCOMPLETE"


def test_expiry_elm_effective_dates():
    # NCL/CMPT/64639 effective 2024-11-20: 2% additional ELM on short index option on expiry day
    def run_elm(valuation_date, expiry_date, scope="index_derivative", kind="option", quantity=-50, spot=24000):
        pos = [{"contract_id": "IDXOPT", "kind": kind, "quantity": quantity, "spot": spot, "expiry_at": f"{expiry_date}T15:30:00+05:30"}]
        rec = [{"contract_id": "IDXOPT", "instrument_scope": scope}]
        return expiry_rule_applicability(pos, rec, f"{valuation_date}T10:00:00+05:30")[0]

    # Pre-effective date: 2024-11-19
    res_pre = run_elm("2024-11-19", "2024-11-19")
    assert res_pre["additional_expiry_elm_rate"] is None
    assert res_pre["modeled_additional_expiry_elm_paise"] is None

    # Post-effective date on expiry day: 2024-11-20
    res_post = run_elm("2024-11-20", "2024-11-20")
    assert res_post["additional_expiry_elm_rate"] == 0.02
    # 24000 spot * 50 qty * 2% = 24,000 INR = 2,400,000 paise
    assert res_post["modeled_additional_expiry_elm_paise"] == 2400000

    # Long option on expiry day: not subject to additional ELM
    res_long = run_elm("2024-11-20", "2024-11-20", quantity=50)
    assert res_long["additional_expiry_elm_rate"] is None

    # Non-expiring option (valuation 2024-11-20, expiry 2024-11-28)
    res_non_exp = run_elm("2024-11-20", "2024-11-28")
    assert res_non_exp["additional_expiry_elm_rate"] is None


def test_calendar_spread_rule_by_expiry():
    # Index derivative calendar spread cutoff: 2025-02-10 (NCL/CMPT/66047)
    def run_cal(valuation_date, expiry_date, scope, kind="option"):
        pos = [{"contract_id": "TEST", "kind": kind, "quantity": -50, "expiry_at": f"{expiry_date}T15:30:00+05:30"}]
        rec = [{"contract_id": "TEST", "instrument_scope": scope}]
        return expiry_rule_applicability(pos, rec, f"{valuation_date}T10:00:00+05:30")[0]

    # Index: before 2025-02-10
    idx_before = run_cal("2025-02-09", "2025-02-09", "index_derivative")
    assert idx_before["calendar_spread_benefit_for_expiring_contract"] is None

    # Index: on 2025-02-10
    idx_on = run_cal("2025-02-10", "2025-02-10", "index_derivative")
    assert idx_on["calendar_spread_benefit_for_expiring_contract"] is False

    # Stock: before 2026-05-04 (NCL/CMPT/72906)
    stock_before = run_cal("2026-05-03", "2026-05-03", "stock_derivative")
    assert stock_before["calendar_spread_benefit_for_expiring_contract"] is None

    # Stock: on 2026-05-04
    stock_on = run_cal("2026-05-04", "2026-05-04", "stock_derivative")
    assert stock_on["calendar_spread_benefit_for_expiring_contract"] is False


def test_missing_span_components_unavailable():
    # If SPAN parameters or arrays are missing, margin components must remain unavailable
    pos = [{"contract_id": "NIFTYFUT", "quantity": 50, "spot": 24000}]
    rec = [{"contract_id": "NIFTYFUT", "instrument_scope": "index_derivative"}]
    res = compliance_checks(pos, {"declared_records": rec})
    assert any(
        f["code"] in ("calendar_spread_margin", "expiry_elm", "delta_position_limit")
        and f["outcome"] == "cannot_assess"
        and f["reason"] == "verified_applicable_rule_and_complete_account_inputs_required"
        for f in res["findings"]
    )
    # Total margin is not fabricated
    assert res.get("total_margin_paise") is None
