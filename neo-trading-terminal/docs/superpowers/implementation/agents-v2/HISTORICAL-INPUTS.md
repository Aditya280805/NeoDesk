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
