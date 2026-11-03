# Options workspace

Open **Options workspace** after signing in. The workspace covers data readiness, covered calls and collars, optional monitoring, scanning, historical imports and backtests, and explanations of saved reports.

## Local setup

From `backend`, install with `python -m pip install -r requirements.txt -c requirements.lock` and run `python -m pip check`. PyArrow is required for Parquet imports. Start the backend using the [repository setup instructions](../README.md) with one worker. From `frontend`, run `npm ci` and `npm run dev`. Use the same browser origin for the UI and authenticated API requests.

Connect Kotak for current broker evidence. The readiness panel describes what the installed adapter can provide. Inspect identity, lot size, settlement, quote side, depth, observation time and coverage before interpreting a strategy or scan. Missing information is reflected in the result status. A saved analysis retains the original observation and assumptions.

The workspace uses deterministic financial engines. The options agent is used only when you explicitly ask it to explain a saved report. That action requires server-side model configuration and cites the selected report and evidence. A configured provider key does not establish free access. See [evaluation and historical source research](OPTIONS_PLATFORM_RESEARCH.md).

## API examples

Send requests to `/api/options-platform` with your existing website session. The examples show the JSON body. IDs come from your own saved evidence and reports.

| Method and path | Example or workflow |
| --- | --- |
| `GET /capabilities` | Inspect the adapter inventory and explicit limitations. |
| `POST /market-snapshot` | `{"underlying":"RELIANCE","exchange":"nse_fo"}`. Use the returned server evidence and selected contract IDs in `POST /analyses`. |
| `POST /baselines` | `{"analysis_id":"<saved analysis ID>","name":"Covered call study"}`. |
| `GET /risk-policy` and `PUT /risk-policy` | Read the current revision before saving. On conflict, review the current revision and reconcile the draft. Unset policy inputs remain unassessable. |
| `PUT /monitoring` | `{"enabled":true,"interval_seconds":60}`. Review status with `GET /monitoring`; read and acknowledge alerts separately using their IDs. |
| `POST /scans` and `POST /backtests` | Provide explicit criteria or entry decisions and assumptions. Poll the returned job ID with the corresponding GET route. Both have a per-job POST cancellation route. |
| `POST /explain` | `{"report_kind":"backtest","report_id":"<saved report ID>","message":"Which assumptions affect this result?"}`. Supported kinds are strategy, scan, alert and backtest. |

For actual portfolio P&L, import a complete user-declared FIFO lot ledger using the workspace example, then explicitly associate its opening fills and exact server-selected inventory with the saved baseline. Ledger coverage must end at the portfolio observation. Broker-day fills can support an explicitly labelled price comparison. Equity and cash flows imported separately are user-declared.

## Historical inputs

The upload form provides an `options-history.1` example. Submit CSV or Parquet up to 10 MiB, a provenance class (`synthetic` or `user_import`), a source and licence declaration, and the expected observation windows for each contract. The API accepts `csv_text` for CSV or `parquet_base64` for Parquet. A validated manifest reports coverage and identifies the immutable import.

Each row has `row_type,record_id,contract_id,timestamp,effective_at,known_at,source`. Supply offset-aware times and unique record IDs. Contract rows identify the instrument, expiry and strike where applicable, lot and deliverable, adjustment identity, and settlement rule. Quote rows give bid/ask and available quantities. Settlement rows give sourced settlement price and rule. Corporate-action rows identify dividends or splits and affected contract terms. Use decimal text in CSV and string or decimal financial columns in Parquet. Use empty or null cells for unavailable values.

Specify an entry decision time, stock and option contract IDs, quantity, opening and expiry costs, adverse slippage, capital and fill policy. Point-in-time replay uses data available at each simulated decision and reports unsupported coverage or settlement. Read the trades, cash ledger and equity curve together with the report limitations.

## Operations and verification

Monitoring is owner opt-in. A missing broker session suspends collection; the UI displays status while server-side jobs run independently. Scans and backtests share a heavy-work slot. Keep exactly one backend process with access to the configured durable SQLite files. Stop the prior process before restarting and preserve those files in backups. Startup recovery can release claims from the stopped process. Lease age alone does not authorize a second worker to take over active work. Reconcile suspended monitoring after broker reauthentication and inspect terminal job status after restarts.

Deploy first to a restricted synthetic environment. Leave `LIVE_TRADING_ENABLED=false` and keep monitoring disabled by default. Enable monitoring per account only after the broker and storage setup is verified. Set `OPTIONS_AGENT_ENABLED=false` when the pilot should omit model explanations. Saved-report explanations depend on existing model configuration. See the [adapter readiness matrix](OPTIONS_DATA_CAPABILITIES.md) for live-verification limitations.

From `backend` run:

```text
python -m pip check
python -m pytest tests -q
python -m app.terminal.options_evals
python -m app.terminal.options_evals --scope portfolio
python -m app.terminal.options_evals --scope portfolio-risk
python -m app.terminal.options_platform_evals
```

From `frontend` run `npm test`, `npm run lint` and `npm run build`. Platform offline evaluation covers deterministic behavior using synthetic fixtures and scoped MCP. Live model comparisons require explicit free-access confirmation, for example `python -m app.terminal.options_platform_evals --mode live-model --variant context --confirm-free-access`. Score the heldout answers using the emitted rubric. Broker verification, model quality and deployment each require independent evidence.
