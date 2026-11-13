"""Pure evaluate_remaining_risk computation module.

Combines immutable captured account bundle with optional proposed strategy into
a unified inventory with explicit netting, stress repricing, and margin verification.
Pure function: no I/O, no broker SDK, no models, no MCP.
"""
from datetime import datetime, UTC, date
from decimal import Decimal
import math

from .analytics_remaining_contracts import CapturedRiskBundle
from .analytics_contracts import StrategyProposal
from .quant_risk import stress_matrix
from .quant_compliance import compliance_checks


def evaluate_remaining_risk(bundle: CapturedRiskBundle, proposal: StrategyProposal | None = None) -> dict:
    """Evaluate combined risk for captured account and optional strategy proposal."""
    if not isinstance(bundle, CapturedRiskBundle):
        raise TypeError("bundle must be a CapturedRiskBundle instance")

    as_of = bundle.as_of
    if proposal is not None:
        if not isinstance(proposal, StrategyProposal):
            raise TypeError("proposal must be a StrategyProposal instance")
        # Validate proposal valuation timestamp against bundle as_of
        try:
            val_dt = datetime.fromisoformat(str(proposal.valued_at))
            if val_dt.tzinfo is None:
                val_dt = val_dt.replace(tzinfo=UTC)
        except Exception as e:
            raise ValueError(f"Cross-evidence or contradictory proposal rejected: invalid valued_at ({e})")

        if val_dt > as_of:
            raise ValueError("Cross-evidence or contradictory proposal rejected: proposal valued in future of evidence")

    # Contradiction check: sources must not follow capture as_of
    for s in bundle.sources:
        if s.observed_at > as_of:
            raise ValueError("Contradictory source timestamps: source observed after capture")

    # Combine positions into unified inventory with single-pass netting per contract_id
    combined_map = {}
    for p in bundle.positions:
        cid = p["contract_id"]
        combined_map[cid] = dict(p)

    # Reference underlying info for borrowing spot/iv/forward if proposal introduces new contract
    underlying_defaults = {}
    for p in bundle.positions:
        u = p.get("underlying")
        if u and u not in underlying_defaults:
            underlying_defaults[u] = p

    cost_paise = None
    if proposal is not None:
        for leg in proposal.legs:
            cid = leg.contract_id
            signed_qty = leg.quantity if leg.side == "BUY" else -leg.quantity
            if cid in combined_map:
                combined_map[cid]["quantity"] = combined_map[cid]["quantity"] + signed_qty
            else:
                # Synthesize position row for the proposal leg
                u = leg.underlying_key
                ref = underlying_defaults.get(u, {})
                spot = ref.get("spot", float(leg.strike))
                forward = ref.get("forward", spot)
                iv = ref.get("iv", 0.20)
                rate = ref.get("rate", 0.07)
                exp_at = datetime(leg.expiry.year, leg.expiry.month, leg.expiry.day, 15, 30, tzinfo=UTC)
                combined_map[cid] = {
                    "contract_id": cid,
                    "underlying": u,
                    "kind": "option",
                    "quantity": signed_qty,
                    "spot": spot,
                    "forward": forward,
                    "strike": float(leg.strike),
                    "expiry_at": exp_at,
                    "iv": iv,
                    "rate": rate,
                    "option_type": leg.option_type,
                }

        # If fee schedule is available in bundle, compute roundtrip cost estimate
        if bundle.fee_schedule:
            # fee schedule provided
            cost_paise = bundle.fee_schedule.get("roundtrip_cost_paise")

    combined_inventory = tuple(combined_map.values())

    # Prepare positions for stress_matrix
    positions_for_stress = []
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
    for p in combined_inventory:
        row = dict(p)
        if row.get("kind") == "option":
            if "tau" not in row:
                exp = row.get("expiry_at")
                if isinstance(exp, str):
                    exp = datetime.fromisoformat(exp).date()
                elif isinstance(exp, datetime):
                    exp = exp.date()
                elif isinstance(exp, date):
                    pass
                else:
                    exp = as_of_date
                days = (exp - as_of_date).days
                row["tau"] = max(0.0001, days / 365.0)
            if "forward" not in row or row["forward"] is None:
                row["forward"] = row["spot"]
            if "iv" not in row or row["iv"] is None:
                row["iv"] = 0.20
            if "rate" not in row or row["rate"] is None:
                row["rate"] = 0.07
        positions_for_stress.append(row)

    # Compute stress matrix
    stress = None
    if positions_for_stress:
        try:
            stress = stress_matrix(positions_for_stress)
        except Exception:
            stress = None

    # Compute aggregate FutEq / delta equivalent
    aggregate_futeq = sum(float(p.get("quantity", 0)) for p in combined_inventory)

    # Compute compliance findings
    compliance_res = None
    if bundle.rules:
        compliance_res = compliance_checks(combined_inventory, {"declared_records": list(bundle.rules), "as_of": as_of.isoformat()})

    # Unavailable reasons tracking
    unavailable_reasons = {}
    if "funds" in bundle.missing_inputs:
        unavailable_reasons["funds_missing"] = "funds_source_unavailable"
    if "overlapping_holdings" in bundle.missing_inputs:
        unavailable_reasons["coverage"] = "overlapping_holdings"
    if bundle.account_coverage != "complete":
        unavailable_reasons["account_coverage"] = f"account_coverage_is_{bundle.account_coverage}"

    # Gross & Net metrics
    worst_pnl = stress["worst_case_scenario"]["pnl"] if (stress and "worst_case_scenario" in stress) else 0.0
    gross_metrics = {
        "aggregate_futeq": aggregate_futeq,
        "gross_stress_worst_case": worst_pnl,
        "max_stress_loss": max(0.0, -worst_pnl),
    }

    net_loss = worst_pnl
    if cost_paise is not None:
        net_loss -= (cost_paise / 100.0)

    net_metrics = {
        "aggregate_futeq": aggregate_futeq,
        "net_stress_worst_case": net_loss,
        "net_max_loss": max(0.0, -net_loss),
        "cost_paise": cost_paise,
    }

    available_margin = None if "funds" in bundle.missing_inputs else bundle.fee_schedule.get("available_margin_paise") if bundle.fee_schedule else None

    # Account coverage verdict: complete ONLY when source coverage proves it and no missing inputs
    final_coverage = bundle.account_coverage
    if bundle.missing_inputs or not bundle.sources:
        if final_coverage == "complete":
            final_coverage = "partial"

    return {
        "schema_version": "remaining-risk.1",
        "coverage": {
            "account_coverage": final_coverage,
            "proposal_included": proposal is not None,
            "position_count": len(combined_inventory),
            "source_count": len(bundle.sources),
            "missing_inputs": bundle.missing_inputs,
        },
        "metrics": {
            "combined_inventory": combined_inventory,
            "gross_metrics": gross_metrics,
            "net_metrics": net_metrics,
            "cost_paise": cost_paise,
            "stress_matrix": stress,
            "compliance_findings": compliance_res["findings"] if compliance_res else [],
            "available_margin_paise": available_margin,
        },
        "unavailable_reasons": unavailable_reasons,
        "source_refs": tuple(f"{s.source}:{s.revision}" for s in bundle.sources),
        "limitations": [
            "Pure deterministic evaluation over captured bundle; no live broker I/O or trading action.",
            "Combined inventory nets quantities once per contract; partial coverage remains unpromoted.",
        ],
    }
