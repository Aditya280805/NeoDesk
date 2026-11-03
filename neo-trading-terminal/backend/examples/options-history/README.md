# Offline historical options data

All prices in `synthetic-collar.csv` are invented. They are useful for covered-call
and collar accounting checks; they are not downloaded NSE data or live evidence.
Do not infer identities, licence rights, expected intervals or settlement rules
from symbols. User imports use the identical schema with `dataset_status=user_import`.

## API

All paths below are relative to `/api/options-platform` and require the existing
authenticated session. The server lifecycle processes queued jobs automatically.

- `POST /historical-imports`: JSON `{format:"csv", csv_text:"...", provenance:"...", licence:"...", dataset_status:"synthetic"|"user_import", expected_intervals:[{contract_id,start,end,interval_seconds}]}`.
- For Parquet use `format:"parquet", parquet_base64:"..."` instead of `csv_text`.
  Base64 is validated; the decoded file has the same 10 MiB maximum as CSV.
- `GET /historical-imports?limit=50&offset=0` and `GET /historical-imports/{id}`:
  private owner manifests, never raw table records. Success status is `validated`.
- `POST /backtests`: use `backtest-request.json`, replacing its dataset UUID with
  the returned import ID. `covered_call` requires removing `put_contract_id`.
- `GET /backtests`, `GET /backtests/{id}`, `POST /backtests/{id}/cancel`.
  Jobs expose `id,status,cursor,event_count,next_due,cancel_requested,error,request,input_hash,report`.
  States are `queued`, `completed`, `cancelled`, `failed`. A completed immutable
  report includes trades, cash ledger, inventory/equity curve, fees/slippage,
  sampled maximum exposure/drawdown, per-entry realised and expiry attribution,
  dataset hash and calculation/cost versions. Cursor progress is durable per event.

Example import body construction in PowerShell (run from `backend`):

```powershell
$csv = Get-Content -Raw examples/options-history/synthetic-collar.csv
$windows = @('S','C','P') | ForEach-Object {
    @{contract_id=$_;start='2026-01-01T09:00:00+05:30';end='2026-01-01T09:01:00+05:30';interval_seconds=60}
}
$body = @{format='csv';csv_text=$csv;provenance='Invented synthetic fixture';licence='Own synthetic data';dataset_status='synthetic';expected_intervals=@($windows)} | ConvertTo-Json -Depth 8
# POST $body as application/json using your authenticated client.
```

The supplied collar fixture settles at 120: opening cash flows are -1001 stock,
+49 call, -31 put, -3 opening fees; physical call delivery receives 1100 and two
option expiry fees cost 2. Final cash/equity is 2112 and net profit 112.
At settlement 80 the put delivers for 900, producing final cash 1912/profit -88.
The same fixture used as a covered call yields cash 2145/profit 145 at 120.

## Shared row table schema (`options-history.1`)

CSV has one header and UTF-8 data. Parquet has the same named columns; every
nonfinancial field is Arrow string/null, every financial field is string,
decimal128/256 or null. Float, bool, nested/list/struct, binary and extension
columns are rejected. No pickle, archives, external file paths or URLs are read.
Files are at most 10 MiB and 100000 physical data rows. Parquet metadata is checked
before batched reading, with a 64 MiB declared uncompressed row-group bound.

Common required fields for every row:
`row_type,record_id,contract_id,timestamp,effective_at,known_at,source`.
The three times are ISO8601 with timezone offset, normalized to UTC. `known_at`
is the earliest knowledge timestamp; contract versions must already be known
and effective at selection time. Source tags must identify the supplied evidence.
Record IDs are unique; contradictory duplicate identities are rejected. Empty
CSV cells mean absent values. Unsupported or extra columns/fields are rejected.
Errors expose sanitized `row,code,message`, with row 2 the first data row.

| row_type | Additional fields |
|---|---|
| contract | `kind` equity/call/put; `underlying_id`; `exchange=NSE`; `currency=INR`; positive integer text `lot_size`; options require `expiry` YYYY-MM-DD and `strike`; `deliverable_quantity=1`; `adjustment_id`; `settlement_rule=physical-european.1` |
| quote | `bid,ask`; optional `bid_quantity,ask_quantity`; bid <= ask; effective_at equals timestamp |
| settlement | `price` underlying event price, `settlement_rule=physical-european.1`, `verified=true`; explicit per-option expiry event |
| corporate_action | `action` cash_dividend/split; `amount`/`ratio` respectively; `adjustment_id`; pipe-separated `adjusted_contract_ids` |

Financial columns are `strike,deliverable_quantity,bid,ask,bid_quantity,ask_quantity,price,amount,ratio`.
They accept finite nonnegative decimal strings up to 12 fractional places and
1e18; booleans, floats and nonfinite values are rejected. Positive split ratios
are required. Decimal scale does not alter the semantic dataset hash. Contract
and quote source timestamps are explicit; there is no inferred exchange calendar.
`expected_intervals` declares every expected quote in each supplied source window.
Missing expected quotes are recorded in manifest coverage; a backtest touching
a selected-leg gap fails with `unsupported_period_quote_gap`. Both decision and
fill must lie inside explicit source windows. No overnight/weekend quotes are
invented. Declare separate session windows rather than a continuous calendar.

Corporate actions support only cash dividends and exact integral splits. Every
affected equity/option ID must have a full contract version with matching
effective_at and adjustment_id, including the current lot/strike/deliverable.
The supported representation has per-current-share strike and deliverable 1;
fractional stock, mixed deliverables and other actions fail closed. The input
provider is responsible for verified adjustment terms. Late adjustment knowledge
and adjustments while an entry is pending are unsupported. Dividends credit cash
once; split updates inventory and cost basis without creating cash.

## Backtest semantics and limits

Selections and schedule are explicit, with at most 100 sequential nonoverlapping
positions. Entries require decision-time quotes known at/before that decision.
The first strictly subsequent simultaneous quote across all selected legs is
used for an atomic matched fill; asynchronous leg execution is unsupported.
Buy at ask plus adverse slippage, sell at bid minus adverse slippage. Depth caps
all legs together to common whole lots. Missing depth defaults to no fill;
`assume_unlimited_depth` explicitly labels a low-confidence offline assumption.
Insufficient purchase funding reduces quantity; premium does not fund purchases.

`mode=owned` requires `initial_inventory:[{contract_id,quantity,acquisition_cost_per_unit}]`;
initial cash is `initial_capital` and stock is marked separately in initial equity.
Owned entries reserve existing stock, incur no invented stock purchase, and use
acquisition basis for per-trade attribution. No broker inventory is inferred.
Opening fees are per filled leg; expiry fees are per settled option; slippage is
per filled unit/leg. Costs are user-declared and versioned `historical-costs.1`.

Every selected option needs an explicit verified (by the dataset provider)
European physical settlement event on its expiry date and within request end.
In-the-money short calls/long puts deliver actual owned stock for strike cash;
no separate intrinsic cash credit is added. OTM stock remains in inventory.
Task2's exact expiry payoff is reused for unadjusted attribution. Corporate-action
entries report actual ledger attribution with theoretical expectation unavailable.
The internal `physical-european.1` identifier describes declared mechanics and
does not certify current NSE rule applicability or licensing.

Valuations use latest known quotes at/before each requested timestamp, start/end
and fills, within `quote_max_age_seconds`. Longs mark bid, shorts ask. Missing
marks create unavailable segments; net profit and maximum drawdown are withheld.
Drawdown reuses the Task3 cashflow-aware unitization function with zero external
flows. Maximum drawdown/exposure are sampled at these valuation times; intraperiod
extremes, early assignment, taxes and annualized returns are not inferred.
Sequential expiry exits close options; residual stock stays in inventory.

Implementation, offline dataset provenance, and live verification are distinct:
reports always say `live_verification=unverified`; synthetic data is labelled.
The worker assumes one backend process; startup recovery never expires a live
lease automatically. Cancellation discards the unpublished event, and restarting
resumes from the last atomically persisted ledger/cursor. Heavy capacity is shared
with scans (20 queued/running jobs; one active worker of either kind).

Dependency references checked: [PyPI PyArrow 20.0.0](https://pypi.org/project/pyarrow/20.0.0/)
and [official ParquetFile API](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html).
The pinned CPython 3.12 Windows wheel is supported by its published classifiers.
