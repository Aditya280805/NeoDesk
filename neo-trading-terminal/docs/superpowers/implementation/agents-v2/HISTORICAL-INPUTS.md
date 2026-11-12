# Historical analytics inputs

When ANALYTICS_TOOLS_ENABLED is enabled, the options chat page exposes a composite analytics panel. Expand Optional historical inputs and supply JSON matching the selected market context. Inputs are user-declared and are not independently verified. A continuation retains the submitted question and input, even if the draft is edited. Start a new analysis to use edited inputs.

Minimal OHLCV example (more observations are needed for most indicators):

```json
{
  "schema_version": "analytics-input.1",
  "context": {"underlying": "NIFTY", "exchange": "nse_fo", "expiry": null},
  "provenance": "Describe the actual data source and extraction method",
  "licence": "Describe your permitted use of these observations",
  "observed_at": "2026-11-10T15:30:00+05:30",
  "bars": [
    {"time": "2026-11-09T15:30:00+05:30", "open": 24000, "high": 24100, "low": 23900, "close": 24050, "volume": null},
    {"time": "2026-11-10T15:30:00+05:30", "open": 24050, "high": 24150, "low": 24000, "close": 24100, "volume": null}
  ]
}
```

Up to 500 ordered bars are supported. Volume may be null; volume-dependent metrics then remain unavailable. Optional vix_history must be positive and align one-to-one with bars.

For portfolio metrics, supply return_dates and cash_flow_adjusted_returns, with one observation per Indian trading day, at least 30 observations for ratios, and at most 5,000 observations. Returns use decimal fractions (0.01 means one percent). The importing user must compute cash-flow adjustments before import; these are not inferred from holdings. Optional benchmark_returns and bank_returns must align one-to-one with the same dates. The daily return frequency is explicit; intraday series are rejected. Missing trade history and eligible cash asset prices leave trade attribution and HRP unavailable.

API users can send historical_input on POST /api/options-agent/analytics/snapshot, or with analytics_mode=true on POST /api/options-agent/unified-chat. For a continuation, send the same historical_input, message and context along with continuation_id and a stable continuation_action_id. Reuse the action ID after a transport failure. Content changes invalidate the continuation. Historical observation dates retain historical meaning; broker and retrieval eligibility still apply on every turn.

Risk imports additionally accept risk_positions (at most 100 unique contracts matching the selected underlying) and risk_history keyed by those contract IDs. Positions require contract_id, underlying, kind (equity/future/option), signed integer quantity in economic units, and positive spot. Options additionally require forward, strike, expiry_at (timestamp with timezone), iv, rate, and uppercase option_type (CALL/PUT). The server calculates ACT/365 time to expiry from expiry_at and observed_at; arbitrary time fractions are not accepted.

Historical observations require date, a consecutive integer session index declared by the source, positive spot, and contract IV for options. Null spot/IV excludes affected scenarios rather than filling values. Each series has at most 5,000 observations and the total at most 100,000. Set risk_history_basis to current_contract_equivalent_source_declared only after validating session coverage and corporate-action/contract adjustment consistency in the source. The server validates ordering and bounds, but does not independently certify that declaration.

Stress returns 28 full-repricing cells. Historical results use actual calendar decay over one/five declared sessions. Each instrument/horizon needs 250 valid scenarios for 95% and 1,000 for 99%; portfolio scenarios use the date intersection. Insufficient 99% history does not remove valid 95% results. These are hypothetical imported-position results; exchange margin and complete-account compliance remain CANNOT_ASSESS.

Declared volatility surface inputs use surface_rows (up to 500), each with contract_id, side (CALL/PUT), strike, expiry_at, forward, rate, fractional iv, integer open_interest in contracts and integer lot_size. All rows for an expiry must use identical forward/rate assumptions. They calculate Black76 Greeks and surface summaries; these declarations do not verify broker instrument identity and never generate verified proposal candidates. Actual expiry timestamps drive ACT/365 time fractions.

For the optional gamma proxy supply surface_spot and gex_sign_assumption="calls_positive_puts_negative". This is a hypothetical inventory-sign scenario, not observed dealer positioning. The signed gamma proxy scales contract OI and lot size to INR hedge notional per one-percent spot move. Forward moves proportionally with spot, with fixed carry and IV. Flip candidates are sign-changing roots searched over 80–120 percent of supplied spot; no crossing means no flip is reported. All results cover supplied contracts only. General model context: https://squeezemetrics.com/monitor/static/guide.pdf (inventory assumptions must be distinguished from observed positions).

Cash HRP imports additionally accept asset_price_dates (ordered daily timezone-aware timestamps) and cash_assets. Each asset has asset_id, kind (cash_equity, cash_etf, option or future), optional sector, nonnegative value_paise, and adjusted_prices aligned exactly with those dates. At least thirty price observations are required, up to 100 assets and 100,000 total price points. Only cash_equity/cash_etf enter long-only HRP; derivative assets are explicitly excluded. Asset kind, adjusted history and valuation are user declarations, not verified portfolio identity. Zero-variance multi-asset histories leave weights unavailable. Sector allocation uses current declared cash values, not derivative notionals or historical sector returns.

Closed-trade metrics use closed_trades with unique trade_id, closed_at and signed integer net_pnl_paise (including costs). Supply an explicit trade_period_start/end bounded by observed_at. Win rate and profit factor are calculated only when trade_history_complete=true and closed trades are present. Breakeven trades count in the win-rate denominator. If there are no losses, profit factor is unavailable, not infinity. Importing closed trades does not infer daily portfolio returns or cash-flow adjustments; those metrics remain independently unavailable until supplied.

Evidence retains the declared closed-trade period, count and completeness status. Numerical denominator policy: daily fractional-return standard deviations at or below 1e-9 (variance <=1e-18) are treated as degenerate for ratios and multi-asset HRP; this prevents constant-return rounding noise from producing extreme Sharpe/beta or arbitrary weights. Sector/trade metrics remain independently usable.

Dated fee scenarios accept fee_transactions (up to 200). Each transaction requires transaction_id, product (option/future/delivery/intraday), side (BUY/SELL/EXERCISE), trade_date, turnover_inr as exact decimal text, turnover_basis and cost_source. Basis is option_premium for option trades, option_intrinsic for option exercise, futures_notional for futures, and cash_trade_value for cash products. Supported dates begin 2024-10-01; future dates are rejected. Amounts are capped at INR 10 billion per transaction to keep aggregated paise within exact browser integer range.

Optional exact decimal text fields brokerage_inr, exchange_rate, sebi_rate and slippage_inr remain unknown when omitted. Rates are fractional (0.00035, not 0.035 percent text). The calculator returns each transaction's components and dated STT version; only fully specified transaction totals can be summed. Exercise uses intrinsic turnover and warns about expiry STT; unsupported exercise-fee components remain unknown. All output is ESTIMATE with per-transaction component-paise rounding, not a broker contract-note reconciliation. Broker/exchange rate inputs are user declarations. A batch is not automatically linked to a strategy or net payoff. Official STT reference: https://www.nseindia.in/static/products-services/equity-derivatives-securities-transaction-tax (checked during implementation).
