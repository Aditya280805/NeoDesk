from datetime import UTC, datetime, date, timedelta
from decimal import Decimal
from uuid import uuid4
import pytest

from app.terminal.analytics_remaining_contracts import CapturedRiskBundle, SourceStamp
from app.terminal.analytics_contracts import StrategyProposal, ProposalLeg
from app.terminal.analytics_remaining_risk import evaluate_remaining_risk


def _sample_source(as_of=None):
    ref = as_of or datetime.now(UTC)
    obs = ref - timedelta(seconds=1)
    return SourceStamp(
        source="NSE",
        revision="rev1",
        observed_at=obs,
        effective_from=obs.date(),
        effective_until=obs.date() + timedelta(days=1),
        checksum="a" * 64,
    )


def _sample_bundle(**changes):
    now = datetime.now(UTC)
    base = dict(
        owner_id=7,
        session_generation="evidence-123",
        as_of=now,
        positions=(
            dict(
                contract_id="NIFTY26MAR24200CE",
                underlying="NIFTY",
                kind="option",
                quantity=50,
                spot=24000.0,
                forward=24050.0,
                strike=24200.0,
                expiry_at=now + timedelta(days=5),
                iv=0.15,
                rate=0.07,
                option_type="CALL",
            ),
        ),
        rules=(),
        fee_schedule=None,
        account_coverage="partial",
        missing_inputs=("funds",),
        sources=(_sample_source(now),),
    )
    base.update(changes)
    if "as_of" in changes and "sources" not in changes:
        base["sources"] = (_sample_source(changes["as_of"]),)
    return CapturedRiskBundle(**base)


def _sample_proposal(evidence_id="evidence-123", valued_at=None, buy_qty=50, sell_qty=50):
    val_time = valued_at or datetime.now(UTC).isoformat()
    legs = (
        ProposalLeg(
            contract_id="NIFTY26MAR24000CE",
            underlying_key="NIFTY",
            exchange="nse_fo",
            currency="INR",
            expiry=date(2026, 3, 26),
            side="BUY",
            quantity=buy_qty,
            lot_size=50,
            strike=Decimal("24000"),
            option_type="CALL",
        ),
        ProposalLeg(
            contract_id="NIFTY26MAR24200CE",
            underlying_key="NIFTY",
            exchange="nse_fo",
            currency="INR",
            expiry=date(2026, 3, 26),
            side="SELL",
            quantity=sell_qty,
            lot_size=50,
            strike=Decimal("24200"),
            option_type="CALL",
        ),
    )
    return StrategyProposal(
        proposal_id=uuid4(),
        evidence_id=uuid4(),
        template="bull_call_spread",
        valued_at=val_time,
        legs=legs,
    )


def test_cross_evidence_proposal_rejected():
    now = datetime.now(UTC)
    bundle = _sample_bundle(as_of=now)
    # Proposal valued after bundle as_of is contradictory
    future_time = (now + timedelta(days=2)).isoformat()
    bad_proposal = _sample_proposal(valued_at=future_time)
    with pytest.raises(ValueError, match="Cross-evidence or contradictory proposal rejected"):
        evaluate_remaining_risk(bundle, bad_proposal)


def test_existing_and_proposed_positions_net_once():
    # Existing: NIFTY26MAR24000CE quantity = +50
    # Proposed leg: NIFTY26MAR24000CE side = 'SELL', quantity = 50 -> net quantity = 0
    now = datetime.now(UTC)
    bundle = _sample_bundle(as_of=now)
    prop = _sample_proposal(valued_at=now.isoformat())
    with pytest.raises(ValueError,match='evidence binding'):
        evaluate_remaining_risk(bundle,prop)


def test_overlapping_holdings_positions_partial():
    # If bundle has duplicate / overlapping holdings or partial coverage, coverage remains partial
    bundle = _sample_bundle(account_coverage="partial", missing_inputs=("overlapping_holdings",))
    res = evaluate_remaining_risk(bundle, None)
    assert res["coverage"]["account_coverage"] == "partial"
    assert "overlapping_holdings" in res["unavailable_reasons"]["coverage"]


def test_missing_funds_or_position_section_not_complete():
    # Complete coverage requires no missing inputs
    bundle = _sample_bundle(account_coverage="partial", missing_inputs=("funds", "positions"))
    res = evaluate_remaining_risk(bundle, None)
    assert res["coverage"]["account_coverage"] != "complete"
    assert res["metrics"]["available_margin_paise"] is None
    assert "funds_missing" in res["unavailable_reasons"]


def test_combined_historical_repricing():
    # Combined inventory should feed stress_matrix producing 28 cells
    now = datetime.now(UTC)
    bundle = _sample_bundle(as_of=now)
    res = evaluate_remaining_risk(bundle)
    stress = res["metrics"]["stress_matrix"]
    assert stress is not None
    assert len(stress["cells"]) == 28
    assert res['metrics']['gross_metrics']['gross_stress_worst_case'] != 0
    assert res['metrics']['gross_metrics']['aggregate_futeq'] is None
    assert res['metrics']['net_metrics']['net_stress_worst_case'] is None
    assert "gross_metrics" in res["metrics"]
    assert "net_metrics" in res["metrics"]
