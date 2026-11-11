# Options chat, MCP and engineering harness

## Unified routing, explicit specialists, and optional external tools

The **Options chat** page exposes four choices in `Chat scope`:
- **Options and trading** (`options_trading_analysis`, `scope: "chain"`) -> `POST /api/options-agent/chat`
- **Portfolio analysis** (`portfolio_analysis`, `scope: "portfolio"`) -> `POST /api/options-agent/portfolio/chat`
- **Portfolio risk** (`portfolio_risk`, `scope: "risk"`) -> `POST /api/options-agent/portfolio/risk/chat`
- **Auto-select** (`master_router`) -> `POST /api/options-agent/unified-chat`

`POST /api/options-agent/unified-chat` accepts `message`, optional `context`
(`underlying`, `exchange`, `expiry`), optional `conversation_id`, and optional
`report_kind` / `report_id`. The tool-less `master_router` Agno team chooses
`chain`, `portfolio`, `risk`, or `clarify`; when a specialist scope is selected,
the backend constructs only that fresh per-request specialist and issues only
that specialist's isolated private MCP capability. Mixed or ambiguous requests
return `scope: "clarify"` (`agent_id: "master_router"`, `conversation_id: null`
when starting a new chat, or preserving the active `conversation_id` on an
ambiguous follow-up) with text only, no private tool calls, no evidence cards,
and no new specialist conversation. Routing adds model calls, allows up to `85` seconds overall, and
classification may still be wrong; users can always pick one of the three
explicit specialists directly.

Conversations remain strictly isolated by scope, specialist, and selected market.
Changing the scope selector or market context in the UI invalidates any pending
request and begins a fresh conversation so late replies cannot leak across scopes.
When a `unified-chat` follow-up switches scope or market on an existing
`conversation_id`, the backend returns HTTP `409` with structured detail:

```json
{"detail": {"code": "conversation_scope_changed", "message": "Start a new conversation after changing scope, specialist, or market selection."}}
```

On `409 conversation_scope_changed`, the **Options chat** UI keeps the typed
draft in the composer, retains existing turns until the user explicitly clicks
**New chat**, and never automatically resubmits.

The root `mcp.json` starts empty. Administrators can configure trusted HTTPS
Streamable HTTP servers with explicit allowed tool names and scopes:

```json
{"servers":{"news":{"url":"https://example.com/mcp","enabled":false,
  "allowed_tools":["search_news"],"scopes":["chain"],"token_env":"NEWS_TOKEN"}}}
```

Set the token in the backend environment, not in this file. Set
`EXTERNAL_MCP_CONFIG` to use a different server-side path. Enabled servers are
connected for the configured scope, and their tools are exposed to the model.
Only authorize services and tools that are trusted, actually read-only, and
appropriate for the user's data: the external service can receive model-chosen
tool arguments, and an allowlist does not verify remote behavior or prevent
disclosure. External tool calls are disabled until a server is explicitly
configured and enabled. Servers cannot access the private MCP capability token.
Provider results are untrusted. The private tools and their evidence checks stay
independent. MCP discovery/connection failure fails the request.

Optional `OPENAI_BACKUP_API_KEY` and `GEMINI_BACKUP_API_KEY` environment
variables configure one same-provider backup each. A recognized 429 retries once
inside the existing request budget and overall agent deadline; other failures do
not trigger rotation. The backup must have its own usable quota. Model-provider
credentials stay server-side. Restart after changing backend environment values.

## Start locally

Use Python 3.12 and Node 24. From `backend/`, create/activate a virtual environment
and install `python -m pip install -r requirements.txt -c requirements.lock`.
The lock constrains direct and transitive versions, with platform markers.
Run `python -m pip check` after installation. Agno's MCP extra requires the
updated FastAPI/Starlette/Uvicorn stack; do not keep the old FastAPI pin.

Add a Gemini key from [Google AI Studio](https://aistudio.google.com/app/apikey)
to the existing server `.env` without overwriting other settings:

```dotenv
OPTIONS_AGENT_PROVIDER=gemini
OPTIONS_AGENT_MODEL=gemini-3.8-flash
GEMINI_API_KEY=your-server-side-key
```

Restart the backend after editing `.env`. Never use a `NEXT_PUBLIC_` variable
for credentials. Select a Gemini Developer API project eligible for the free tier;
quotas and availability depend on that project. The app does not enable billing.
For OpenAI instead, set `OPTIONS_AGENT_PROVIDER=openai`,
`OPTIONS_AGENT_MODEL=gpt-4.1-mini` and `OPENAI_API_KEY`. With provider `auto`
(the default), a configured Gemini key takes precedence, then an OpenAI key.
The corresponding model defaults are used when `OPTIONS_AGENT_MODEL` is unset.
Provider/model mismatches appear as setup errors. A request never switches
providers after a quota or authentication failure. `OPTIONS_AGENT_PROVIDER=ollama`
wires local OpenAI-compatible loopback transport (`http://127.0.0.1:11434/v1`,
default `qwen3:4b`, `:cloud` tags blocked, `900` completion-token budget);
however, local model availability, GPU capacity, and live Ollama answer quality
remain deferred and unmeasured.

`OPTIONS_AGENT_ENABLED=true` enables the feature; false leaves the rest of the
terminal available. `OPTIONS_MCP_PORT=8766` is a loopback-only internal port.
Set it to a different free port on conflict, or zero to allocate a free port.
Do not proxy or expose this listener. Keep the public Uvicorn server at one
worker: broker sessions, capabilities and limits are process-local.

Run `./run-local.ps1` from the project root. An optional `-PythonPath` selects a
different virtual environment. This implementation was verified with
`./run-local.ps1 -PythonPath backend/.venv-harness/Scripts/python.exe` because
OneDrive locked files in the existing environment during dependency installation.
The old environment's Starlette/Uvicorn versions were restored.

Sign in to an individual website account, connect Kotak, and open **Options
chat**. Choose **Options and trading**, **Portfolio analysis**, **Portfolio risk**,
or **Auto-select** under `Chat scope`. In option-chain or pre-routed Auto mode,
select the underlying, exchange and optional expiry; blank expiry uses the
provider's default. Changing the scope or market selection starts a new
conversation. In **Auto-select**, periodic snapshot refresh stays disabled until
routing lands on a concrete specialist (`chain`, `portfolio`, or `risk`).
Legacy shared-password login alone cannot select a user's broker connection.
Snapshots work without a model key; AI answers need both that key and real
broker data. No sample data is substituted in the live feature.

## Architecture

Browser -> authenticated options API -> `AGENT_REGISTRY` per-request specialist
factory + `RequestHarness` -> private MCP client -> Streamable HTTP MCP server ->
SnapshotService -> user's Kotak session. The MCP listener shares the backend
process and starts/stops with its lifespan. A startup failure marks options
monitoring unavailable without taking down the site.

Active specialist registration lives in `backend/app/terminal/agent_registry.py`
with per-request factory construction in `specialist_agents.py` and
`unified_chat.py` (the legacy `options_monitor` catch-all agent and `build_agent`
factory are retired):

| Agent ID | Scopes | Endpoint | Private MCP Tool | UI Evidence Renderer |
|---|---|---|---|---|
| `options_trading_analysis` | `chain` | `POST /api/options-agent/chat` | `get_option_snapshot` | Market snapshot table/card |
| `portfolio_analysis` | `portfolio` | `POST /api/options-agent/portfolio/chat` | `get_portfolio_analysis_snapshot` | `PortfolioEvidence` (no risk fields) |
| `portfolio_risk` | `risk` | `POST /api/options-agent/portfolio/risk/chat` | `get_portfolio_risk_report` | `PortfolioRiskPanel` (no account sections) |
| `master_router` | `clarify` or delegates | `POST /api/options-agent/unified-chat` | None (tool-less router) | Selected by validated scope; none for `clarify` |
| `options_trading_analysis` | `strategy`, `scan`, `alert`, `backtest` | `POST /api/options-platform/explain` | `get_{kind}_report` | Saved report view |

A random 65-second internal capability binds user, scope/market, and run.
Every MCP HTTP request checks it; browser origins are rejected. The capability
is revoked when the request ends and is never included in prompts or responses.
This is an internal service protocol, not an externally connectable OAuth MCP
service. Discovery and tool calls still use real MCP protocol messages.

Each specialist chat first retrieves validated evidence through its scoped MCP
tool. The agent receives the same immutable snapshot or report as user-role data
and can inspect it through that tool. A per-request cache prevents inconsistent
evidence or duplicate broker fetches. Manual **Refresh snapshot** calls
`/api/options-agent/snapshot` (`chain`) or `/api/options-agent/portfolio/snapshot`
(`portfolio` / `risk`) through MCP and never calls the model.

Existing status/snapshot/chat/conversation endpoints remain alongside the
specialist and unified routes. `/status` reports `model_configured`, `mcp_ready`,
`enabled`, `provider`, `api_key_env`, `setup_error`, `generation_token_budget`,
and `registered_agents`. Specialist responses return `agent_id`, `run_id`,
`parent_run_id` (linking `master_router` parent runs to delegated specialist
runs), and scope-isolated citations (`snapshot_ids`, `evidence_ids`, or
`risk_report_ids`).
`GET /api/options-agent/runs/{run_id}` returns sanitized owner-scoped
diagnostics (`stages`, `status`, `duration_ms`, versions, snapshot/evidence/report
references, `risk_diagnostics`, and `harness` trace metrics). Admitted failed
requests include `X-Options-Run-Id` in the response headers for diagnostic lookup.
Admission failures have no agent run ID.
Snapshots add `identity_verification`; fields absent from broker metadata are
explicitly unverified. Supplied identity contradictions are rejected. Known
expiry spellings are normalized for comparison; expiry selection sent to Kotak
still needs the provider-supported format.

## Harness engineering: where the controls live

| Layer | Implementation | Control |
|---|---|---|
| Development | AGENTS.md, requirements.lock, verification suite | Reproducible checks and read-only architecture rules |
| Data | options_snapshot.py, portfolio_risk_*.py | Shape/number validation, identity checks, deterministic Decimal math |
| Permission/tool | options_mcp.py, agent_scope.py, options router | Individual identity, scoped capability, projection-isolated tool allowlists, no caller user ID |
| Execution | options_agent.py, unified_chat.py, agent_harness.py, options_model.py | Stage/cumulative deadlines, concurrency/rate/tool/token/context budgets, controlled failures |
| Context/output | specialist_agents.py (`AGENT_REGISTRY`) + scoped answers | Per-request specialist factories, versioned instructions, untrusted data separation, validated UUID citations |
| Evaluation | backend/evals, specialist_evals.py, options_evals.py, options_platform_evals.py | Offline contract/MCP replay plus separate opt-in live-model/live-broker evaluation |
| Diagnostics | option_agent_runs SQLite table | Stages, status, duration, versions, `parent_run_id`, `harness` trace (`utf8-bytes-divided-by-3`), no prompts/secrets |

Limits: one active request per user across explicit specialists, unified routing,
and snapshot refresh; six chat/routing attempts/minute/user; four total active
options requests; snapshot refresh at most once/five seconds/user.
OpenAI and Ollama have `900` completion tokens; Gemini has `4096` generation
tokens including thinking. Context sizing uses a conservative UTF-8 byte rule
(`utf8-bytes-divided-by-3`) bounded by `input_limit=24000` and `context_limit=32768`.
Each stage allows at most `3` model attempts (`3` total requests in explicit flows;
`6` total across router + specialist in `Auto-select`). MCP permits at most `3`
reads (`read_tool`: initial prefetch plus at most `2` model tool calls). Gemini
function-call IDs and thought signatures are preserved between model requests.
Model HTTP timeout is `30` seconds, overall request deadline is `60` seconds for
explicit specialists and `85` seconds for `Auto-select`, and SDK retries remain
disabled outside same-provider HTTP 429 backup-key rotation. Unknown provider
token usage keeps its full reservation. Kotak SDK transport timeout is ten seconds.
Synchronous broker work stays off the event loop; cancellation retains capacity
until its worker actually finishes. A timeout does not imply the thread stopped.

Sanitized trace interpretation (`GET /api/options-agent/runs/{run_id}` and
`option_agent_runs`): `parent_run_id` links `master_router` parent runs to
delegated specialist runs (and stays identical to `run_id` on direct explicit or
clarification runs). Admitted failures attach `X-Options-Run-Id`. The `harness`
block records allowlisted counters only (`attempts`, `tool_reads`, `broker_fetches`,
`cache_hits`, `delegations`, `token_estimate_method`, and `stages.{router,specialist}`
with `attempts`, `generation_spent`, `input_token_estimate`, `reported_output`,
`unknown_usage`, `duration_ms`), without prompts, raw provider errors, or row data.

Prompts use at most four earlier successful turns. Structured model output must
cite only current snapshot, evidence, or risk-report IDs for the active scope.
Metrics displayed in the evidence/snapshot panels come from deterministic
backend code. This validates evidence references, not the truth of every
sentence: generated prose still requires evaluation and human judgment.

Successful conversations retain their exact snapshots. Additive SQLite tables
record admitted successful/failed runs without storing failed conversation
turns, provider exceptions or credentials. Authentication and admission errors
are returned directly rather than creating an agent run. Third-party Agno
logging during options runs is sanitized. There is no separate diagnostics UI.
Conversation history remains stored, but this release does not add a conversation
list or automatic resume after a page reload.

## Monitoring behavior and limitations

Refresh runs every 60 seconds while the page is visible, pauses when hidden,
and stops on request failure. Its state appears on the page. Refreshing does
not rewrite previous chat evidence. Earlier snapshots are retained and labelled
on refresh failure; age over 90 seconds is labelled older. A changed selection
invalidates late replies. Data retrieval times are not exchange timestamps;
exchange freshness is always unverified, including after market close.

OI totals and ratio cover returned strikes only. Missing OI stays unavailable;
IV, Greeks and bid/ask spreads are unavailable. Trading, personalized strategy
recommendations, background alerts, external MCP clients, additional agents and
automatic self-modification are outside this release.

## Verification and release gates

From `backend/` using the constrained harness environment:

```powershell
.venv-harness\Scripts\python.exe -m pip check
.venv-harness\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.venv-harness\Scripts\python.exe -m app.terminal.specialist_evals --mode offline
.venv-harness\Scripts\python.exe -m app.terminal.options_evals --scope chain
.venv-harness\Scripts\python.exe -m app.terminal.options_evals --scope portfolio
.venv-harness\Scripts\python.exe -m app.terminal.options_evals --scope portfolio-risk
.venv-harness\Scripts\python.exe -m app.terminal.options_platform_evals
```

From `frontend/`: `npm test`, `npm run lint`, `npm run build`.
Docker installs with the same constraints and includes the evaluation fixtures.

Offline replay tests deterministic specialist/MCP contracts, schema
validation, routing invariants, and arithmetic (`model_evaluated=false`).
`specialist_evals --mode offline` covers 18 split cases across `chain`,
`portfolio`, `risk`, and `clarify`, while `options_evals` tests scope-specific
datasets and `options_platform_evals` covers strategy/scan/alert/backtest
explainers. The API integration tests run Agno/OpenAI and Agno/Gemini
serialization against controlled model HTTP responses and broker fixtures.
They verify plumbing and controls, NOT live model prose quality, Ollama local
weights/availability, or private broker connectivity.

Explicit real-model evaluation (opt-in only; uses the selected provider's API
quota or local endpoint and may incur charges on a billed project):

```powershell
python -m app.terminal.specialist_evals --mode live-model
python -m app.terminal.options_evals --mode live-model
```

Live-model checks evaluate evidence citations plus regex regression checks for
ratio, missing OI, missing Greeks, execution refusals, provider injection, and
context switching. Regex rubrics are a regression aid; review answers before
treating them as a comprehensive quality score. Live Ollama benchmarking remains
deferred and unmeasured.

Explicit real-broker smoke: start the website, sign in and connect Kotak, set
`OPTIONS_SMOKE_TOKEN` in your shell to your own authenticated website token,
then run `python -m app.terminal.options_evals --mode live-broker`.
Optional `--base-url`, `OPTIONS_SMOKE_UNDERLYING` and `OPTIONS_SMOKE_EXPIRY` select
the site and contract. It only fetches a snapshot; it does not call the model.
Remove the shell variable afterward. Never paste the token into chat or commit it.

Before production enablement, require passing offline/CI checks, inspect the
model evaluation results with the configured model, and verify one real broker
snapshot and one real chat answer. Missing credentials leave those live gates
unverified; offline tests must not be reported as substitutes.

## Troubleshooting

- `mcp_ready=false`: check OPTIONS_AGENT_ENABLED and loopback port availability;
  install the complete constrained dependency set and restart the backend.
- `model_configured=false`: use the `api_key_env` and `setup_error` status fields
  to correct the selected provider's server configuration, then restart.
- Gemini quota/auth/model errors: check the selected AI Studio project's quota,
  key restrictions and model access. There is no provider fallback during a run
  outside optional same-provider backup keys (`OPENAI_BACKUP_API_KEY` /
  `GEMINI_BACKUP_API_KEY`).
- 401: sign in to an individual account; shared login does not confer identity.
- 409 `conversation_scope_changed`: follow-up no longer matches the bound
  specialist/scope/market. The UI keeps your typed draft and offers **New chat**
  without auto-resubmitting.
- 409 concurrency / 429 rate limit: wait for the current request, 5-second
  refresh cooldown, or 6/min rate window to clear.
- 503: verify Kotak connection, selected market/expiry and model access. Inspect
  owner-scoped run metadata (`GET /api/options-agent/runs/{run_id}`) for the
  last stage; raw provider text is suppressed.
- 504: deadline reached (`60`s explicit, `85`s Auto-select); a broker worker may
  still hold its slot until completion.

Future additions should begin with deterministic strategy tools and paper
validation, then separately designed scheduling/alerts. Keep model evolution
outside the live runtime until versioned evaluations and promotion rules exist.

## Phase 1 portfolio evidence

Portfolio analysis and portfolio risk now run as separate isolated specialists
backed by `AGENT_REGISTRY` and scoped MCP projections under the unified
admission harness. Select **Portfolio analysis** or **Portfolio risk** (or
**Auto-select**) on the **Options chat** page; chain, portfolio, and risk
sessions maintain separate conversations. The existing manual trading UI remains
separately authorized and is not an agent tool.

| Scope | Agent ID | Public authenticated routes under /api/options-agent | Private MCP tool |
|---|---|---|---|
| Chain | `options_trading_analysis` | `POST /snapshot`, `POST /chat` | `get_option_snapshot` |
| Portfolio | `portfolio_analysis` | `POST /portfolio/chat` | `get_portfolio_analysis_snapshot` |
| Risk | `portfolio_risk` | `POST /portfolio/risk/chat` | `get_portfolio_risk_report` |
| Auto-select | `master_router` | `POST /unified-chat` | None (tool-less router) |
| Manual refresh | — | `POST /portfolio/snapshot` (empty body) | Scoped UI refresh (non-agent) |
| All | — | `GET /status`, `GET /conversations/{id}`, `GET /runs/{id}` | No execution or user-selection tool |

Public identity comes from the individual signed-in account. Portfolio tool
arguments are empty; scope/user overrides and cross-scope conversation IDs are
rejected. The current session generation binds collection, cached reads and
publication. Disconnect, reconnect, login and authentication expiry invalidate
that generation. Failed or obsolete requests cannot publish old evidence.

Portfolio sections are holdings, positions, funds and orders, each independently
available, partial, unavailable or invalid. Empty arrays are valid empty evidence;
missing quantity/amount is null, never zero. Funds are provider amounts, not a
computed account equity. Provider MTM and calculated cash-flow P&L remain separate
because periods/bases differ. Holdings and positions may overlap: do not add them
into an account total. Order sides/statuses may be UNKNOWN. Ambiguous identities
block derivation/aggregation; contradictions invalidate affected evidence. Lot
sizes never silently replace unknown multipliers. Catalogue matches alone do not
prove complete derivative identity. Exchange timestamps/freshness remain unknown.

The portfolio.v1 wire format uses exact decimal strings or null (including
quantities, money and percentages). Arithmetic uses Decimal with 64-digit local
precision; money rounds half-up to two decimal places, with versioned formula and
input-path provenance. Calculations that overflow become unavailable. The legacy
/api/live portfolio adapter retains existing fields using nullable finite numbers.

Four broker endpoints are collected sequentially off the event loop. Evidence is
non-atomic: retrieval start/finish and observation times do not imply simultaneous
holdings, positions, orders and funds. A 15-second session cache avoids duplicate
collection; a reuse gets a new evidence ID and cache age while retaining source
observation times. Within one MCP capability, repeated reads return identical
evidence. Refresh never rewrites earlier chat evidence. All specialists share
one active request/user, four global requests, six chat/routing attempts/minute,
and a five-second refresh interval floor. Capability expiry is 65 seconds, at
most three reads including prefetch; model tools are capped at two. The three-
model-request (six total in `Auto-select`), 30-second HTTP, 60-second explicit /
85-second Auto deadline, and provider token budgets above apply.
Cancellation keeps admission occupied until synchronous work actually finishes.

Portfolio questions are 1–2000 characters; answers are at most 12000 characters
and must reference exactly the current evidence UUID. Extra portfolio body fields
are forbidden. Each broker section is capped at 1000 rows and 1 MiB serialized
payload; excess sections are invalid, never silently complete. Human-readable
description strings over 160 characters are shortened with a quality issue.
Numeric values and identifiers are never parsed or matched from shortened
prefixes; oversized semantic fields are unavailable or invalid instead.
Raw provider payloads and exception text are not public evidence.

Run both deterministic datasets explicitly from backend (offline does not read
.env, call a model, or connect to a broker):

```powershell
.venv-harness/Scripts/python.exe -m pip check
.venv-harness/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
.venv-harness/Scripts/python.exe -m app.terminal.options_evals
.venv-harness/Scripts/python.exe -m app.terminal.options_evals --scope portfolio
```

The original six-case chain dataset is unchanged. portfolio-evals.v1 is synthetic,
held out from prompt examples, with independently hand-checked decimal operands.
Offline reports verify real Streamable HTTP MCP contracts/calculations and say
model_evaluated=false. This does not measure model answer quality. Reports export
portfolio-review.v1 human criteria for completeness, interpretation and abstention;
structured references and numeric concepts only provide automated regression aids.
Live answers must be manually scored against that rubric. Cost is null/unknown;
no price table is supplied, so unknown usage or pricing is never zero cost.

After explicitly authorizing quota/cost use and configuring the server provider,
run `python -m app.terminal.options_evals --scope portfolio --mode live-model`.
This uses synthetic observations with the configured real model, reports available
token usage, and exports answers for review. For your authenticated broker snapshot,
set OPTIONS_SMOKE_TOKEN locally as described above, then run
`python -m app.terminal.options_evals --scope portfolio --mode live-broker`.
The broker mode calls no model. A real website portfolio chat is a separate gate.
A local key alone proves neither free-tier eligibility nor successful live use.

For partial evidence inspect section state/issues, reconnect and refresh as
appropriate; do not interpret unavailable as an empty account. On session-changed
errors, sign in/connect again and start a new request. On payload_limit, use broker
support to inspect the source response; the agent cannot reconstruct omitted rows.
For port conflict, authentication, quota, 429 and timeout handling use the
troubleshooting steps above. Keep one public backend worker and the MCP listener
on loopback without browser origins. No secrets belong in prompts, fixtures or logs.

Strategy tools, scanners, risk engines, background scheduling/alerts, external MCP
clients, automatic trading and self-modification remain later phases.

Task 7 review correction: broker smoke reports use scope-specific *-broker-smoke.v1
check versions, with dataset/rubric versions null and explicitly not applicable.
They fetch a real authenticated snapshot rather than replaying an evaluation
dataset or scoring a model answer. Each report includes the HTTP/reference check,
measured latency and unavailable (null) usage/cost.

## Phase 2 portfolio risk monitoring

`POST /api/options-agent/portfolio/risk/chat` (specialist `portfolio_risk`,
`risk.1`) and manual refresh (`POST /api/options-agent/portfolio/snapshot`)
produce an immutable portfolio-risk.v1 report tied to the current evidence UUID
and captured policy revision; `POST /api/options-agent/portfolio/chat`
(`portfolio_analysis`, `analysis.1`) omits risk findings to keep analysis and
risk boundaries isolated. Settings start unset; disabled, unavailable and stale
checks remain visible. Threshold equality passes; a pass is not account safety.
Reports preserve exact decimal strings/null and do not derive account margin or
account P&L from row totals. The live Kotak adapter currently supplies neither
documented total-margin nor broker-day account-P&L semantics; those checks
remain unavailable until a verified adapter mapping exists.

Run the third offline gate from backend:

```powershell
.venv-harness/Scripts/python.exe -m app.terminal.options_evals --scope portfolio-risk
```

portfolio-risk-evals.v1 reuses the independent Task 3 arithmetic operands and adds
missing/zero, stale, disabled/unset and policy/order authority cases over real
private loopback MCP. It reports calculation portfolio-risk.1, prompt risk.1,
null model version and cost, and model_evaluated=false. The separate fixed
portfolio-risk-explanation.v1 rubric lives in
backend/evals/portfolio_risk_explanation_rubric.json. Its human scoring remains
pending; synthetic citation/schema and transport checks do not measure generated
explanation quality or a real model's resistance to injection. Risk-scope
live-model and live-broker modes are intentionally unavailable; the existing
portfolio modes retain their separate opt-in behavior and do not score this risk
rubric. No live model or Kotak checks were run for Phase 2.

Production MCP evaluation logs emit an allowlisted `portfolio_risk` JSON event on success or evaluation failure; publication stores the same shared metadata in owner-scoped run detail under `risk_diagnostics`. Failed runs retain a sanitized failure stage (evaluation, model/output, or publication); a valid financial breach remains distinct from an operational failure. Offline replay uses the same runtime-neutral builder. Diagnostics expose only report/evidence IDs, captured revision, calculation
version, enabled/assessed counts, duration, outcome and failure stage. A valid
breach is distinct from an operational evaluation failure. Never log financial
values, raw provider payloads or credentials.

Report maintenance is explicit and dry-run first. From backend, substitute the
existing application database path and a chosen retention age:

```powershell
.venv-harness/Scripts/python.exe -m app.terminal.portfolio_risk_maintenance --database PATH --older-than-days 90
```

Review the candidate count, then repeat with --apply only when deletion is wanted.
Reports referenced in conversations or run records are preserved. Policy edits do
not rewrite historical reports. No maintenance deletion was run during validation.

Controlled Task 5 browser evidence verified conflict/reload, captured revisions,
zero/null display and failed-refresh stale retention. A synthetic hidden-page
fixture held the request counter stable for 74 seconds and resumed on visibility;
actual OS visibility and background timer throttling remain unverified. See the
phase ledger task-5-cua-results.md and task-5-cua-stale.png.

New portfolio history rows store the normalized snapshot and `risk_report_id`; owner-scoped history reads hydrate the canonical immutable report. Existing embedded-report and pre-risk rows remain readable. Maintenance scans structured evidence/run detail and any legacy JSON answers; ordinary plaintext answer prose does not block pruning. Invalid structured reference storage still conservatively blocks deletion.
