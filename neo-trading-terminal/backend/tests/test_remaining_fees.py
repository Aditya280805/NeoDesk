from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError

from app.terminal.indian_charges import (
    statutory_charges,
    declared_fee_estimate,
    reconcile_proposal_costs,
)
from app.terminal.analytics_contracts import StrategyProposal, ProposalLeg
from app.terminal.quant_proposals import spread_payoff


def _sample_proposal(quantity=50, lot_size=50):
    legs = (
        ProposalLeg(
            contract_id="NIFTY26MAR24000CE",
            underlying_key="NIFTY",
            exchange="nse_fo",
            currency="INR",
            expiry=date(2026, 3, 26),
            side="BUY",
            quantity=quantity,
            lot_size=lot_size,
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
            quantity=quantity,
            lot_size=lot_size,
            strike=Decimal("24200"),
            option_type="CALL",
        ),
    )
    return StrategyProposal(
        proposal_id="11111111-1111-1111-1111-111111111111",
        evidence_id="22222222-2222-2222-2222-222222222222",
        template="bull_call_spread",
        valued_at="2026-03-20T10:00:00Z",
        legs=legs,
    )


def test_entry_exit_different_effective_dates():
    proposal = _sample_proposal()
    entry_quotes = {
        "NIFTY26MAR24000CE": {"bid": "100.00", "ask": "100.00"},
        "NIFTY26MAR24200CE": {"bid": "40.00", "ask": "40.00"},
    }
    exit_quotes = {
        "NIFTY26MAR24000CE": {"bid": "150.00", "ask": "150.00"},
        "NIFTY26MAR24200CE": {"bid": "20.00", "ask": "20.00"},
    }
    # Entry on 2026-03-31 (STT rate 0.001 for option sell)
    # Exit on 2026-04-01 (STT rate 0.0015 for option sell under modern schedule)
    fee_schedule = {
        "brokerage_per_order_inr": "20.00",
        "exchange_rate": "0.00035",
        "sebi_rate": "0.000001",
    }
    costs = reconcile_proposal_costs(
        proposal,
        entry_quotes=entry_quotes,
        exit_quotes=exit_quotes,
        entry_date="2026-03-31",
        exit_date="2026-04-01",
        fee_schedule=fee_schedule,
    )
    assert costs["entry"]["schedule_version"] == "stt.2024-10-01"
    assert costs["exit"]["schedule_version"] == "stt.2026-04-01"
    # Entry sell turnover = 40 * 50 = 2000 INR -> STT = 2 INR (200 paise)
    assert costs["entry"]["stt_paise"] == 200
    # Exit sell turnover = 150 * 50 = 7500 INR -> STT = 7500 * 0.0015 = 11.25 INR (1125 paise)
    assert costs["exit"]["stt_paise"] == 1125
    assert costs["roundtrip_cost_paise"] is not None
    assert costs["roundtrip_cost_paise"] > 0


def test_exercise_assignment_charges():
    # Intrinsic turnover = (spot - strike) * qty = 200 * 50 = 10,000 INR
    # Exercise charges should apply STT on exercise (0.125% pre-Apr 2026, 0.15% post-Apr 2026)
    charges_pre = statutory_charges(
        product="option",
        side="EXERCISE",
        turnover_inr="10000",
        trade_date="2026-03-25",
        brokerage_inr="20",
        exercise_charge_inr="50",
    )
    assert charges_pre["stt_paise"] == 1250  # 0.125% of 10000 INR = 12.50 INR = 1250 paise
    assert charges_pre["itm_expiry_stt_trap_warning"] is True
    assert charges_pre["exercise_charge_paise"] == 5000  # 50 INR = 5000 paise

    charges_post = statutory_charges(
        product="option",
        side="EXERCISE",
        turnover_inr="10000",
        trade_date="2026-04-02",
        brokerage_inr="20",
        exercise_charge_inr="50",
    )
    assert charges_post["stt_paise"] == 1500  # 0.15% of 10000 INR = 15.00 INR = 1500 paise
    assert charges_post["schedule_version"] == "stt.2026-04-01"


def test_fee_rounding_matches_dated_contract_note():
    # Contract note scenario:
    # Trade: Sell 1 lot options @ 200, lot 50 -> turnover = 10,000 INR on 2024-10-15
    # Brokerage: 20 INR
    # Exchange rate: 0.00035 (3.50 INR)
    # SEBI rate: 0.000001 (0.01 INR)
    # STT: 0.001 (10.00 INR)
    # GST: 18% on (20 + 3.50 + 0.01) = 4.2318 -> 4.23 INR (423 paise)
    # Stamp: 0 on sell
    # Total = 20.00 + 10.00 + 3.50 + 0.01 + 4.23 = 37.74 INR (3774 paise)
    res = statutory_charges(
        product="option",
        side="SELL",
        turnover_inr="10000",
        trade_date="2024-10-15",
        brokerage_inr="20",
        exchange_rate="0.00035",
        sebi_rate="0.000001",
    )
    assert res["brokerage_paise"] == 2000
    assert res["stt_paise"] == 1000
    assert res["exchange_paise"] == 350
    assert res["sebi_paise"] == 1
    assert res["stamp_paise"] == 0
    assert res["gst_paise"] == 423
    assert res["total_paise"] == 3774


def test_unknown_broker_fee_blocks_net_total():
    # When brokerage is unknown (None), statutory_charges must not assume 0!
    res = statutory_charges(
        product="option",
        side="SELL",
        turnover_inr="10000",
        trade_date="2024-10-15",
        brokerage_inr=None,
    )
    assert res["brokerage_paise"] is None
    assert res["gst_paise"] is None
    assert res["total_paise"] is None

    # In spread_payoff: when roundtrip_cost_paise is None, net figures must be None
    proposal = _sample_proposal()
    quotes = {
        "NIFTY26MAR24000CE": {"bid": "99.00", "ask": "100.00"},
        "NIFTY26MAR24200CE": {"bid": "40.00", "ask": "41.00"},
    }
    payoff = spread_payoff(proposal, quotes, roundtrip_cost_paise=None)
    assert payoff["gross_max_profit_paise"] is not None
    assert payoff["net_max_profit_paise"] is None
    assert payoff["net_max_loss_paise"] is None


def test_invalid_lot_or_quote_rejected():
    proposal = _sample_proposal()
    quotes_valid = {
        "NIFTY26MAR24000CE": {"bid": "99.00", "ask": "100.00"},
        "NIFTY26MAR24200CE": {"bid": "40.00", "ask": "41.00"},
    }

    # Invalid quote: ask < bid
    quotes_inverted = {
        "NIFTY26MAR24000CE": {"bid": "101.00", "ask": "100.00"},
        "NIFTY26MAR24200CE": {"bid": "40.00", "ask": "41.00"},
    }
    with pytest.raises(ValueError, match="Invalid bid-ask quotes"):
        spread_payoff(proposal, quotes_inverted)

    # Invalid quote: negative quote
    quotes_negative = {
        "NIFTY26MAR24000CE": {"bid": "-10.00", "ask": "100.00"},
        "NIFTY26MAR24200CE": {"bid": "40.00", "ask": "41.00"},
    }
    with pytest.raises(ValueError, match="Invalid bid-ask quotes"):
        spread_payoff(proposal, quotes_negative)

    # Invalid quote: non-finite
    quotes_nan = {
        "NIFTY26MAR24000CE": {"bid": "nan", "ask": "100.00"},
        "NIFTY26MAR24200CE": {"bid": "40.00", "ask": "41.00"},
    }
    with pytest.raises(ValueError):
        spread_payoff(proposal, quotes_nan)

    # Missing contract in quotes
    quotes_missing = {"NIFTY26MAR24000CE": {"bid": "99.00", "ask": "100.00"}}
    with pytest.raises(ValueError, match="Missing quote"):
        spread_payoff(proposal, quotes_missing)

    # Invalid lot / structure (rejected by Pydantic / model validation)
    with pytest.raises((ValueError, ValidationError)):
        _sample_proposal(quantity=0, lot_size=50)

    with pytest.raises((ValueError, ValidationError)):
        _sample_proposal(quantity=50, lot_size=0)

    with pytest.raises((ValueError, ValidationError)):
        _sample_proposal(quantity=75, lot_size=50)

    # Debit spread bounds violation (debit < 0)
    quotes_negative_debit = {
        "NIFTY26MAR24000CE": {"bid": "20.00", "ask": "20.00"},
        "NIFTY26MAR24200CE": {"bid": "50.00", "ask": "50.00"},
    }
    with pytest.raises(ValueError, match="Quotes inconsistent with debit spread bounds"):
        spread_payoff(proposal, quotes_negative_debit)

    # Debit spread bounds violation (debit > width; width is 200)
    quotes_excessive_debit = {
        "NIFTY26MAR24000CE": {"bid": "250.00", "ask": "250.00"},
        "NIFTY26MAR24200CE": {"bid": "10.00", "ask": "10.00"},
    }
    with pytest.raises(ValueError, match="Quotes inconsistent with debit spread bounds"):
        spread_payoff(proposal, quotes_excessive_debit)
