# Options MCP harness implementation ledger

Approved specification: options chat, private MCP server and engineering harness in this conversation.

## Tasks

1. Baseline and dependency/lifecycle compatibility.
2. Shared validated snapshot service.
3. Private MCP transport and request capabilities.
4. Agno execution budgets, structured evidence and run records.
5. Website monitoring behavior.
6. Offline/live evaluations, CI, documentation and final review.

## Decisions and evidence

- Baseline: existing options tests: 17 passed from backend directory.
- Ruling: work in the existing checkout on feature/options-mcp-harness; the approved foundation includes uncommitted and untracked files. Copying only HEAD into a worktree would lose required implementation. Preserve all unrelated changes; do not stage or commit the mixed checkout.
- Pre-flight: snapshot contract is shared by MCP, agent responses, history and frontend. Preserve existing fields and add evidence/identity metadata.
- Dependency finding: Agno 3.1.10 MCP extra requires MCP >=2.1 and FastMCP >=4; these require newer Starlette/Uvicorn than the existing FastAPI pins. Verify an updated compatible stack in a separate virtual environment and run the full regression suite.
- Environment: installation into the existing OneDrive virtual environment failed on locked Starlette files. Use backend/.venv-harness for the new stack; repair the original environment separately.

## Completion evidence

- Tasks 1-6 complete. Existing public chat/history fields preserved; new owner-scoped run endpoint and evidence/identity metadata added.
- Compatibility: FastAPI 0.162.0, Uvicorn 0.54.0, Agno 3.1.10, MCP 2.3.0, FastMCP 4.1.4; constrained transitive versions; pip check passes.
- Original environment restored to FastAPI 0.115.12 / Starlette 0.46.2 / Uvicorn 0.34.2 after locked-file installation failure. Updated stack verified in .venv-harness, selectable through run-local.ps1 -PythonPath.
- Data tests first exposed identity contradictions, nested malformed fields, boolean values and overflowing sums; implementations now pass.
- Actual MCP initialize/discover/call tests verify identity binding, immutable cached evidence, invalid/expired/revoked credentials, rejected tool arguments and origins, tool budget, bind failure and cancellation retaining broker capacity.
- Real authenticated API -> Agno -> loopback MCP -> broker fixture -> structured evidence integration passed with controlled OpenAI HTTP; no paid model calls.
- Final backend suite: 140 passed in 58.74 seconds. Frontend: 5 tests passed; lint and static build passed. Dependency check passes.
- Offline evaluation: 6/6 fixture cases passed, explicitly model_evaluated=false.
- Real headless Chrome against isolated fixture backend passed authenticated page, MCP snapshot, chat evidence, visible refresh, hidden pause, failed-refresh stop, selection reset, volume/OI columns; no page errors. Screenshot: docs/options-mcp-harness-preview.png.
- Fresh reviewer: no P0/P1 findings. Fixed P2 conflicting expiry aliases and minor expiry display alias with failing-then-passing tests. Fixed minor failed-run discoverability via X-Options-Run-Id response header and owner lookup test.
- Regression fixes: shared-app nested lifespans reuse listener owner; exception during application lifespan always closes listener (failing-then-passing lifecycle test).
- Deferred minor: saved conversations have no reload/resume UI; documented in OPTIONS_AGENT.md. Existing history API/storage remain usable.
- Unverified external gates: actual paid model quality/prompt-injection outcomes, real Kotak chain/answer, GitHub/Linux CI execution and deployment. No OPENAI_API_KEY is configured locally. No external services, orders, pushes or deployments were performed.
- Repository-wide diff whitespace check reports preexisting whitespace in unrelated changes. Targeted tracked-file check for this task passes after removing the README trailing blank line.

## Phase 0: Gemini provider support

- Gemini Developer API and OpenAI are selectable with `OPTIONS_AGENT_PROVIDER`; auto prefers a configured Gemini key. The default Gemini model is `gemini-3.8-flash`.
- Google Gen AI SDK is pinned. Its compatible Tenacity constraint is 9.1.4. Gemini uses one provider attempt per model request, a 30-second model timeout and a 4096-token generation budget including thinking.
- Agno's Gemini formatter omits function-call IDs when replaying tool calls. The local adapter restores those IDs and keeps thought signatures, verified by a real SDK serialization test with controlled HTTP and the real MCP loopback transport.
- Provider errors are mapped to sanitized quota, authentication, permission and model-access messages; no provider fallback is attempted during a request.
- Offline fixtures cannot verify a real Gemini account's model access, quota or response quality. Live model and Kotak gates remain separate.
- Fresh review found a missing-usage budget gap; a failing test reproduced it, then the adapter was changed to reserve the remaining generation allowance when usage fields are incomplete. The focused suite passed 19/19.
- Phase 0 verification: backend 152 passed; offline evaluation 6/6 with model_evaluated=false; pip check passed; frontend 5 tests, lint and production build passed. The local environment currently selects Gemini 3.5 Flash and has a nonblank Gemini key; provider/model configuration validates without revealing the key. No live Gemini or Kotak request was made, so account access and broker behavior remain unverified.

## Phase 1: approved design and implementation plan

- User approved the one-agent, modular-services, private-MCP design on 2026-10-28.
- Approved design: `docs/superpowers/specs/2026-10-28-modular-options-agent-design.md`.
- Detailed seven-task plan: `docs/superpowers/plans/2026-10-28-portfolio-evidence-phase-1.md`.
- Plan covers typed portfolio evidence, deterministic normalization, session-aware collection, server-enforced MCP scope, one agent runner, portfolio chat UI and evaluation/release checks. Self-review mapped each Phase 1 requirement to a task and test.
- Implementation is tracked below. Existing Phase 0 test results are not Phase 1 verification results.

## Phase 1 Task 1: typed portfolio evidence (2026-10-28)

- Added strict Pydantic portfolio.v1 snapshot, section, row, issue and provenance contracts, plus an internal transport observation envelope. Reusable row fields remain nullable for unknown identity, quantities, prices, sides, order metadata and separately named provider/calculated P&L.
- Decimal parsing distinguishes missing, zero and exact source precision; rejects boolean/malformed/nonfinite values and rejects negative values unless allowed. Public decimal fields apply finite signed or nonnegative validation according to their role.
- Deterministic serialization emits decimal strings/null, UUIDs and timestamps and revalidates mutable containers before JSON output. Public models forbid extra raw payload/exception fields; issue codes use an explicit safe vocabulary.
- Red: backend-focused pytest collection failed because app.terminal.portfolio_contracts did not yet exist. Green: validated .venv-harness interpreter, tests/test_portfolio_contracts.py, 9 passed in 0.24 seconds. No live services, environment files, staging or commits.
- Scope: contract tests only; normalization, collector ownership/session enforcement, broader integration and real model/broker behavior remain for subsequent tasks.

## Phase 1 Task 7: evaluation and release evidence (2026-10-28)

- Implemented --scope chain|portfolio; default chain and its six original cases remain unchanged. Portfolio has 11 synthetic held-out cases, portfolio-evals.v1, independent decimal expectations and exported portfolio-review.v1 human rubric. Replay uses production normalization and actual loopback Streamable HTTP MCP, including portfolio-only discovery and rejected caller-user overrides. Offline mode disables .env loading and calls no model/broker. Reports include versions, per-case checks, latency, available model token usage and unknown/null cost.
- Added red-first evaluation/CLI compatibility tests: initial two failures demonstrated missing portfolio runner and unsupported --scope; focused green was 4 passed in 30.61s.
- Required local gates: validated backend/.venv-harness/Scripts/python.exe; pip check: No broken requirements found; full pytest tests -q -p no:cacheprovider: 226 passed in 102.20s; default chain CLI: 6/6; portfolio CLI: 11/11, both model_evaluated=false. Frontend npm test: 23 passed; npm run lint: exit 0; npm run build: exit 0, 14 pages exported. CI already runs all backend tests and default CLI; portfolio CLI is additionally exercised by the new full-suite CLI test, so workflow unchanged.
- Setup/API, scope/tool matrix, decimal/provenance, session-generation/cache, section limitations, bounds, troubleshooting, live commands and deferred phases are documented in docs/OPTIONS_AGENT.md. Strategy/scanner/risk/background work is deferred.
- Release artifacts: ../.superpowers/sdd/2026-10-28-portfolio-evidence-phase-1/task-7-report.md plus task-7-chain-eval.json and task-7-portfolio-eval.json. Targeted git diff --check exited 0; target source files are pre-existing untracked, so explicit whitespace inspection was also performed (no trailing whitespace in six target files).
- At the Task 7 checkpoint, fresh Task 7 and whole-phase reviews were pending. Their final outcomes are recorded in the closeout section below. Live gates were unverified: provider/model account access and quota/free-tier eligibility, live-model generated-answer rubric, authenticated Kotak snapshot, and real website portfolio chat. No live service request, secret inspection, staging, commit, reset or unrelated edit was performed.

## Task 7 review fix round 1

- Addressed material reporting finding from task-7-review.md: live-broker uses scope-specific chain-broker-smoke.v1 / portfolio-broker-smoke.v1 check versions, null dataset/rubric versions with explicit not-applicable metadata, per-check HTTP/reference success and latency, null unavailable usage/cost. Chain command and legacy broker summary fields remain compatible.
- Regression controls HTTP using httpx.MockTransport and exercises actual CLI main() report shaping; no live broker/model or environment-file access.
- Red command (backend cwd): `.venv-harness/Scripts/python.exe -m pytest tests/test_portfolio_evals.py -k broker_smoke_cli -q -p no:cacheprovider` → 1 failed, 2 deselected in 3.83s (incorrect options-evals.v1).
- Final focused command (backend cwd): `.venv-harness/Scripts/python.exe -m pytest tests/test_portfolio_evals.py tests/test_options_evals.py -q -p no:cacheprovider` → 5 passed in 30.49s, exit 0. No broader optional reruns. Earlier full-suite/frontend results apply to the original Task7 baseline; focused result verifies this reporting correction.
- docs/OPTIONS_AGENT.md explains smoke metadata applicability. At this checkpoint, fresh re-review remained controller-owned; its final outcome appears below. All live gates remained unverified.

## Phase 1 final closeout (2026-10-29)

- All seven implementation tasks passed their scoped spec/quality reviews. The whole-phase review found six Important integration defects. One unified fix wave corrected async generation/deadline and cancellation handling, semantic-field truncation, malformed order sides, manual refresh cache bypass, earliest source observation time and contradictory lot-size reconciliation. A scoped rereview reproduced a final cancellation window before database commit; the follow-up check closed it, with four cancellation/deadline regression variants passing. The rereview approved all six findings with no unresolved Critical/Important breakage.
- The portfolio chat busy text now names portfolio evidence. Documentation distinguishes shortened human-readable descriptions from exact numeric and identifier fields. The optional stale badge and stronger history-survivor assertions remain deferred; explicit source/cache/section labels are present.
- Final current-code gates: backend `.venv-harness/Scripts/python.exe -m pytest tests -q -p no:cacheprovider` passed **241 tests in 106.78 seconds**. Frontend `npm test` passed **23 tests**, `npm run lint` exited 0, and `npm run build` exited 0 with TypeScript and 14 static pages. Offline chain evaluation passed **6/6** and portfolio evaluation **11/11**; both reported `model_evaluated=false` and unknown/null cost. `pip check` found no broken requirements.
- Evidence and review details are retained in `../.superpowers/sdd/2026-10-28-portfolio-evidence-phase-1/phase1-final-fix-report.md`, `phase1-final-fix-rereview.md` and `progress.md`. No live broker/model calls or secret inspection occurred; live Kotak connectivity and payload completeness, provider quota, human-scored model answers and a real website portfolio chat remain unverified release gates. No staging, commits, reset or push were performed.

## Phase 2 Task 6 evaluation record (2026-10-30)

- Added explicit --scope portfolio-risk offline replay: 9/9 synthetic cases over
  real private Streamable HTTP MCP. Task 3 arithmetic operands retain independent
  exact expected outcomes; missing/zero, abstention, stale observations, disabled
  and unset settings, and policy/order authority boundaries are exercised.
- Separate fixed portfolio-risk-explanation.v1 human rubric is exported with
  model_scored=false. Explicit dataset/calculation/prompt/model version fields,
  model_evaluated=false and null cost prevent claims of generated model quality.
  Risk live modes remain unavailable; existing chain/portfolio modes are retained.
- Allowlisted evaluation diagnostics contain IDs, revision, calculation version,
  counts, duration, outcome and failure stage. Sentinel tests exclude balances,
  provider payloads and credentials; operational failures differ from breaches.
- RED: correct backend-cwd new test run failed twice on missing risk runner and
  diagnostic function. GREEN: focused evaluation suite 7 passed in 47.51s; final
  four risk tests passed in 12.14s. pip check: no broken requirements found.
  Separate CLI artifacts: chain 6/6, portfolio 11/11, portfolio-risk 9/9; all
  model_evaluated=false and null cost. Full backend result is in task-6-report.md.
- Frontend evidence is the unchanged Task 5 code's prior 39/39 tests, lint exit 0
  and build exit 0. No redundant frontend gates were run for backend/docs changes.
- Controlled browser evidence and screenshot are task-5-cua-results.md and
  task-5-cua-stale.png in the phase ledger. Synthetic hidden-page request count
  remained stable for 74 seconds and resumed afterward; actual OS visibility /
  timer throttling remains unverified. Conflict/reload, report revision races,
  zero/null and stale retention passed in that controlled UI.
- Setup documents dry-run-first report pruning and unavailable live Kotak margin /
  account P&L semantics. No live broker/model, secret inspection, maintenance
  deletion, staging, commit, reset, push or deployment was performed. Task and
  whole-phase review/ledger completion remain controller-owned.

- Required full backend gate: `.venv-harness/Scripts/python.exe -m pytest tests -q
  -p no:cacheprovider` passed **367 tests in 213.83s**, exit 0. Final focused
  verification also covers the added production prompt/action-schema assertions.

## Phase 2 final closeout (2026-10-31)

- All six task spec/quality reviews passed. Broad review found two Important and three Minor issues; one unified fix wave addressed all five. Independent scoped rereview approved plaintext-compatible pruning, shared production risk diagnostics, reference-only history storage and owner-scoped hydration, expanded evaluator/UI control flow, and configured missing/unsupported margin/loss replay. No actionable new breakage remained.
- Canonical history reads in async chat run through an admitted worker with deadline, cancellation and session-generation fences. Regression tests demonstrate event-loop progress, admission retention until blocked reads exit, and no new successful publication after cancellation, deadline or logout. Legacy embedded and pre-risk history remain supported.
- Final current-code backend gate: **378 passed in 180.06s**, using `.venv-harness/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --tb=short`; `pip check` found no broken requirements. Earlier focused final-fix tests passed 87; continuation integration/eval tests passed 28 and legacy portfolio-agent compatibility passed 32. The first full final-fix run caught an outdated 9-case CLI expectation; it was corrected to the intentional 11-case replay before the final green run.
- Frontend final-fix gates: **39 tests passed**, lint and production build passed. Separate offline replay passed **chain 6/6, portfolio 11/11, portfolio-risk 11/11**; all report `model_evaluated=false` and null cost. Frontend/offline evidence was retained after the backend-only hydration continuation; the final full backend includes replay CLI compatibility.
- Evidence: `../.superpowers/sdd/2026-10-29-portfolio-risk-phase-2/final-fix-report.md`, `final-fix-rereview.md`, `final-fix-backend-tests.txt`, frontend/eval artifacts and `progress.md`. The ledger retains all five execution rulings and snapshot provenance. The checkout and local evidence remain as-is; no staging, commits, reset, push or deployment occurred.

## Options platform completion

- The private workspace integrates readiness, deterministic strategy reports, owner monitoring, scanners, historical backtests and explicit saved-report explanations. See [setup and operations](OPTIONS_PLATFORM.md) and [research and evaluation](OPTIONS_PLATFORM_RESEARCH.md).
- A controlled browser exercised synthetic strategy and baseline actions, monitor opt-in and alerts, scanner results, CSV upload, backtest results, report explanation and client-side validation. The local plan ledger retains the synthetic request traces, review reports and verification outputs.
- Broker verification, human-scored live model quality and deployment remain separate from the offline release gates.
- Live Kotak connectivity and account margin/P&L semantics, generated model explanation quality, human-scored held-out answers, actual OS background visibility/timer behavior and production-scale pruning performance remain unverified. Controlled browser visibility evidence uses synthetic events; offline protocol/schema tests do not establish live readiness. No live broker/model calls or secret inspection occurred.
