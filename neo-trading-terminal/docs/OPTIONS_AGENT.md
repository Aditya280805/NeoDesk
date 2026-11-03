# Options chat, MCP and engineering harness

## Unified routing and optional external tools

`POST /api/options-agent/unified-chat` accepts `message`, optional `context`
(`underlying`, `exchange`, `expiry`) and optional `conversation_id`. An Agno
route-mode team chooses chain, portfolio, or clarification; the backend then
creates only the selected user's existing scoped capability. The router is
instructed to request clarification for mixed or unclear requests, but its
classification may be wrong; users can use the existing scope-specific endpoints
available. Changing scope requires a new conversation. Routing adds model calls
and has its own limits and 25-second deadline. The existing website continues
to use its explicit scope selector and scope-specific endpoints.

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
providers after a quota or authentication failure.

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
chat**. Select the underlying, exchange and optional expiry. Blank expiry uses
the provider's default. Changing these controls starts a new conversation.
Legacy shared-password login alone cannot select a user's broker connection.
Snapshots work without a model key; AI answers need both that key and real
broker data. No sample data is substituted in the live feature.

## Architecture

Browser -> authenticated options API -> runtime harness/Agno -> private MCP
client -> Streamable HTTP MCP server -> SnapshotService -> user's Kotak session.
The MCP listener shares the backend process and starts/stops with its lifespan.
A startup failure marks options monitoring unavailable without taking down the site.

The chain tool is `get_option_snapshot`, with no model-controlled arguments.
Portfolio capabilities expose only `get_portfolio_snapshot` (see Phase 1 below).
A random 65-second internal capability binds user, selected market and run.
Every MCP HTTP request checks it; browser origins are rejected. The capability
is revoked when the request ends and is never included in prompts or responses.
This is an internal service protocol, not an externally connectable OAuth MCP
service. Discovery and tool calls still use real MCP protocol messages.

Each chat first retrieves validated evidence through MCP. The agent receives
the same immutable snapshot as user-role data and can inspect it through its
MCP tool. A per-request cache prevents inconsistent evidence or duplicate
broker fetches. Snapshot refresh also goes through MCP and never calls the model.

Existing status/snapshot/chat/conversation endpoints remain. Status adds
`model_configured`, `mcp_ready`, `enabled`, `provider`, `api_key_env`,
`setup_error` and `generation_token_budget`. Chat adds `snapshot_ids`.
`GET /api/options-agent/runs/{run_id}` returns sanitized diagnostics to its owner.
Admitted failed requests include `X-Options-Run-Id` in the response headers for
diagnostic lookup. Admission failures have no agent run ID.
Snapshots add `identity_verification`; fields absent from broker metadata are
explicitly unverified. Supplied identity contradictions are rejected. Known
expiry spellings are normalized for comparison; expiry selection sent to Kotak
still needs the provider-supported format.

## Harness engineering: where the controls live

| Layer | Implementation | Control |
|---|---|---|
| Development | AGENTS.md, requirements.lock, CI | Reproducible checks and read-only architecture rules |
| Data | options_snapshot.py | Shape/number validation, identity checks, deterministic OI arithmetic |
| Permission/tool | options_mcp.py and options router | Individual identity, scoped capability, tool allowlist, no caller user ID |
| Execution | options_agent.py, options_model.py | Deadlines, concurrency/rate/tool/token budgets, controlled failures |
| Context/output | build_agent and AgentAnswer | Versioned instructions, untrusted data separation, validated snapshot references |
| Evaluation | backend/evals and options_evals.py | Offline replay plus separate opt-in real-model evaluation |
| Diagnostics | option_agent_runs SQLite table | Stages, status, duration, versions, snapshot reference, tool count and available tokens |

Limits: one active request per user; six chat attempts/minute/user; four total
active options requests; snapshot refresh at most once/five seconds/user.
OpenAI has 900 completion tokens; Gemini has 4096 generation tokens including
thinking. Both allow at most three model requests and two agent tool calls.
MCP permits one initial prefetch plus those two calls. Gemini function-call IDs
and thought signatures are preserved between model requests.
Model HTTP timeout is 30 seconds, overall request deadline 60 seconds, and
provider retries are disabled. Missing token usage reserves the remaining
completion budget. Kotak SDK transport timeout is already ten seconds.
Synchronous broker work stays off the event loop; cancellation retains capacity
until its worker actually finishes. A timeout does not imply the thread stopped.

Prompts use at most four earlier successful turns. Structured model output must
cite exactly the current snapshot ID. Metrics displayed in the snapshot panel
come from code. This validates evidence references, not the truth of every
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

From `backend/` using the updated environment:

```powershell
python -m pip check
python -m pytest tests -q
python -m app.terminal.options_evals
```

From `frontend/`: `npm test`, `npm run lint`, `npm run build`.
The repository-root GitHub workflow runs these on pushes and pull requests.
Docker installs with the same constraints and includes the evaluation fixtures.

Offline replay tests six cases through the actual MCP transport. The API
integration tests run real Agno/OpenAI and Agno/Gemini serialization against controlled model
HTTP responses and broker fixtures. They verify plumbing and controls, not
actual model reliability or private broker connectivity.

Explicit real-model evaluation (uses the selected provider's API quota and may
incur charges on a billed project; fixture market data):

```powershell
python -m app.terminal.options_evals --mode live-model
```

This checks evidence plus basic answer concepts/refusals for ratio, missing OI,
missing Greeks, execution requests, provider injection and context switching.
Regex rubrics are a regression aid; review answers before treating them as a
comprehensive quality score. The default offline report says model_evaluated=false.

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
  key restrictions and model access. There is no provider fallback during a run.
- 401: sign in to an individual account; shared login does not confer identity.
- 409/429: wait for the current request or refresh/rate window to finish.
- 503: verify Kotak connection, selected market/expiry and model access. Inspect
  owner-scoped run metadata for the last stage; raw provider text is suppressed.
- 504: deadline reached; a broker worker may still hold its slot until completion.

Future additions should begin with deterministic strategy tools and paper
validation, then separately designed scheduling/alerts. Keep model evolution
outside the live runtime until versioned evaluations and promotion rules exist.

## Phase 1 portfolio evidence

Portfolio chat is a second scope of the same Agno agent and admission harness.
Select **Portfolio** on the options page; chain selection and portfolio sessions
have separate conversations. The existing manual trading UI remains separately
authorized and is not an agent tool.

| Scope | Public authenticated routes under /api/options-agent | Private MCP tool |
|---|---|---|
| Chain | POST /snapshot, POST /chat | get_option_snapshot |
| Portfolio | POST /portfolio/snapshot (empty body), POST /portfolio/chat | get_portfolio_snapshot |
| Both | GET /status, GET /conversations/{id}, GET /runs/{id} | No execution or user-selection tool |

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
evidence. Refresh never rewrites earlier chat evidence. Both scopes share one
active request/user, four global requests, six chat attempts/minute and a
five-second refresh interval floor. Capability expiry is 65 seconds, at most
three reads including prefetch; model tools are capped at two. The three-model-
request, 30-second HTTP, 60-second overall and provider token budgets above apply.
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

Portfolio responses now include an immutable portfolio-risk.v1 report tied to the
current evidence UUID and captured policy revision. Settings start unset; disabled,
unavailable and stale checks remain visible. Threshold equality passes; a pass is
not account safety. Reports preserve exact decimal strings/null and do not derive
account margin or account P&L from row totals. The live Kotak adapter currently
supplies neither documented total-margin nor broker-day account-P&L semantics;
those checks remain unavailable until a verified adapter mapping exists.

Run the third offline gate from backend:

```powershell
.venv-harness/Scripts/python.exe -m app.terminal.options_evals --scope portfolio-risk
```

portfolio-risk-evals.v1 reuses the independent Task 3 arithmetic operands and adds
missing/zero, stale, disabled/unset and policy/order authority cases over real
private loopback MCP. It reports calculation portfolio-risk.1, prompt portfolio.2,
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
