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
