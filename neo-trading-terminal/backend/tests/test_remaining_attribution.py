from decimal import Decimal
import pytest
import numpy as np

from app.terminal.quant_attribution import (
    portfolio_attribution,
    cash_sector_performance,
    cash_flow_adjusted_returns,
    reconcile_trade_inventory_cash,
)


def test_deposit_and_withdrawal_do_not_inflate_return():
    # Day 0: start with 100,000 INR
    # Day 1: asset price flat. Deposit of 50,000 INR arrives. Total portfolio value = 150,000 INR.
    # Naive return would be (150000 - 100000) / 100000 = +50% (wrong!).
    # Cash-flow-adjusted return must be 0.0%.
    # Day 2: asset price grows 10%. Portfolio value = 165,000 INR.
    # Day 3: withdrawal of 65,000 INR. Portfolio value = 100,000 INR. Asset price flat.
    daily_values = [100000.0, 150000.0, 165000.0, 100000.0]
    # Cash flows: (day_index, amount): day 1 deposit +50k, day 3 withdrawal -65k
    cash_flows = {1: 50000.0, 3: -65000.0}
    returns = cash_flow_adjusted_returns(daily_values, cash_flows)
    assert len(returns) == 3
    # Day 1 return: flat price, deposit ignored -> return 0.0
    assert returns[0] == pytest.approx(0.0, abs=1e-6)
    # Day 2 return: 10% gain -> (165000 - 150000) / 150000 = 0.10
    assert returns[1] == pytest.approx(0.10, abs=1e-6)
    # Day 3 return: flat price, withdrawal ignored -> return 0.0
    assert returns[2] == pytest.approx(0.0, abs=1e-6)


def test_sector_contributions_reconcile_total():
    # Two sectors: Financials and Tech
    # Forward-linked sector contributions must sum to the total cash sleeve return
    dates = [f"2026-03-{i:02d}" for i in range(1, 11)]
    from datetime import date
    dt_dates = [date(2026, 3, i) for i in range(1, 11)]
    assets = [
        {
            "asset_id": "HDFCBANK",
            "sector": "Financials",
            "adjusted_prices": [100.0 + i * 0.5 for i in range(10)],
            "beginning_values_paise": [5000000] * 9,
        },
        {
            "asset_id": "INFY",
            "sector": "Tech",
            "adjusted_prices": [150.0 + i * 1.0 for i in range(10)],
            "beginning_values_paise": [5000000] * 9,
        },
    ]
    res, reason = cash_sector_performance(assets, dt_dates, complete=True)
    assert reason is None
    assert res is not None
    total_ret = res["cash_sleeve_return"]
    sector_sum = sum(s["linked_contribution"] for s in res["sectors"].values())
    assert sector_sum == pytest.approx(total_ret, abs=1e-9)


def test_trade_inventory_reconciles_cash():
    # Trade inventory cash reconciliation:
    # Initial cash: 100,000 INR
    # Fills:
    # 1. Buy 100 shares @ 150 INR = -15,000 INR + 20 INR fee (2000 paise)
    # 2. Sell 100 shares @ 165 INR = +16,500 INR + 20 INR fee (2000 paise)
    # Realized PnL = +1500 INR gross - 40 INR fees = 1460 INR net
    # Ending cash should be: 100,000 - 15,020 + 16,480 = 101,460 INR
    fills = [
        {"side": "BUY", "quantity": 100, "price": 150.0, "fees_paise": 2000},
        {"side": "SELL", "quantity": 100, "price": 165.0, "fees_paise": 2000},
    ]
    recon = reconcile_trade_inventory_cash(
        initial_cash_inr=100000.0,
        fills=fills,
    )
    assert recon["gross_realized_pnl_inr"] == pytest.approx(1500.0)
    assert recon["total_fees_inr"] == pytest.approx(40.0)
    assert recon["net_realized_pnl_inr"] == pytest.approx(1460.0)
    assert recon["ending_cash_inr"] == pytest.approx(101460.0)
    assert recon["reconciled"] is True


def test_short_history_does_not_disable_independent_metrics():
    # If returns series is shorter than 30 observations (e.g. 15 observations):
    # Sharpe/Sortino/Calmar/Omega are unavailable due to insufficient history,
    # BUT max_drawdown, max_drawdown_duration, and ulcer_index must STILL be computed!
    short_returns = [0.01, -0.02, 0.015, -0.01, 0.005, -0.008, 0.012, -0.005, 0.02, -0.015, 0.008, -0.003, 0.01, -0.02, 0.01]
    assert len(short_returns) == 15
    res = portfolio_attribution(short_returns)
    # Dependent metrics unavailable
    assert res["sharpe"] is None
    assert res["sortino"] is None
    assert res["calmar"] is None
    assert res["unavailable_reasons"]["sharpe"] == "insufficient_verified_return_history"
    # Independent metrics available!
    assert res["max_drawdown"] is not None
    assert res["max_drawdown"] > 0
    assert res["max_drawdown_duration"] is not None
    assert res["ulcer_index"] is not None


def test_missing_benchmark_only_disables_alpha():
    # Full 40 return observations, but no benchmark provided
    returns = [0.005 * (1 if i % 2 == 0 else -0.8) for i in range(40)]
    res = portfolio_attribution(returns, benchmark=None)
    # Portfolio-only metrics must be available
    assert res["sharpe"] is not None
    assert res["sortino"] is not None
    assert res["max_drawdown"] is not None
    assert res["ulcer_index"] is not None
    # Only benchmark-dependent metrics are disabled
    assert res["beta_nifty50"] is None
    assert res["alpha_nifty50_annualized"] is None
    assert res["unavailable_reasons"]["beta_nifty50"] == "missing_benchmark"
    assert res["unavailable_reasons"]["alpha_nifty50_annualized"] == "missing_benchmark"
