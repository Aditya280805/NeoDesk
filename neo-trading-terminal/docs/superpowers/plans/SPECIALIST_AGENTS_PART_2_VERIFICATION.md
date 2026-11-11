# Specialist Agents Part 2 — Verification Record

## Repository & Baseline State

- **Branch:** `codex/local-specialist-agents`
- **Part 1 Baseline Commit:** `0047dc4 docs(specialist-agents): update Part 1 handoff and progress with code-fix SHA`
- **Round 1 Integration & Pre-Round-2 Remediation Commit:** `c1ade55 feat: complete specialist agent integration and cleanup`
- **Verified Code Commit (`HEAD` during code/test/doc verification):** `f93286b fix(specialist-agents): harden scope guards, snapshotError alert, VM tests, and docs`
  - *(Note: `f93286b` is the exact verified code+tests+docs commit SHA. The commit updating this verification document sits immediately on top of `f93286b` and touches only `SPECIALIST_AGENTS_PART_2_VERIFICATION.md`.)*
- **Scope & Remediation Notes:**
  - **Pre-Round-2 Part 1 debug-audit remediation & Round 1 edits landed in `c1ade55` (`0047dc4` -> `c1ade55`):**
    - Pre-Round-2 backend/audit remediation (outside Part 2 UI integration scope): `backend/app/terminal/{agent_harness.py,agent_scope.py,options_agent.py,options_mcp.py,unified_chat.py}`, `backend/tests/{test_audit_regressions.py,test_portfolio_agent.py,test_portfolio_risk_integration.py,test_specialist_mcp.py}`, `frontend/src/lib/api.ts`, `frontend/tests/session.test.cjs`, and `docs/superpowers/plans/{2026-11-11-specialist-agents-part-2-basic-integration.md,2026-11-11-specialist-agents-debug-audit.md}`.
    - Round 1 Part 2 UI integration & docs: `frontend/src/pages/options-chat.tsx`, `frontend/src/styles/options-chat.css`, `frontend/tests/specialist-agents.test.cjs`, `frontend/tests/portfolioRisk.test.cjs`, `docs/OPTIONS_AGENT.md`, `docs/superpowers/plans/SPECIALIST_AGENTS_PART_2_VERIFICATION.md`.
  - **Round 2 bounded integration, test, and doc fixes landed in `f93286b` (`c1ade55` -> `f93286b`):**
    - `frontend/src/pages/options-chat.tsx`: replaced `<p className="error options-chat-error" role="alert">` for `snapshotError` with `<div className="error options-chat-error" role="alert"><span>...</span></div>` to avoid `globals.css` `p` style collisions; strengthened `validateReply` to reject `'risk_inputs'` on `portfolio_snapshot` and `'risk_snapshot'` on `portfolio` replies, and to reject `'portfolio_snapshot'` on `risk` raw replies as well as `'holdings'`, `'positions'`, `'funds'`, `'orders'`, and `'sections'` on `risk_snapshot`.
    - `frontend/tests/specialist-agents.test.cjs`: updated `loadTs` / `createHarness` to execute all loaded TypeScript modules in one shared `vm` context so `e instanceof Error` in `lib/api.ts:63` evaluates `true` for errors thrown by `options-chat.tsx`; updated validation tests to assert exact `validateReply` and `ApiError` error messages instead of falling back to `'Request failed. Please try again.'`; added tests for `snapshotError` non-`<p>` alert rendering and `risk`/`portfolio` leaked-field rejections.
    - `backend/tests/test_portfolio_risk_integration.py`: committed the working-tree test assertion fix at line 221 (`'snapshot.portfolio.1'` replacing retired `'portfolio.2'`, matching `options_agent.py:191`, `test_portfolio_agent.py:57`, and `2026-11-11-specialist-agents-debug-audit.md:70`).
    - `docs/OPTIONS_AGENT.md`: updated line 442 from stale `prompt portfolio.2` to `prompt risk.1` matching `options_evals.py:310` (`specialist_scope('risk', None).prompt_version`).

---

## Executed Verification Commands & Observed Results (Verified on Code Commit `f93286b`)

### 1. Backend Dependency Integrity (`pip check`)
- **Command (from `neo-trading-terminal/backend`):**
  `.\.venv-harness\Scripts\python.exe -m pip check`
- **Result:** Exit code `0` — `No broken requirements found.`

### 2. Backend Full Pytest Suite
- **Command (from `neo-trading-terminal/backend`):**
  `.\.venv-harness\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`
- **Result:** Exit code `0` — `658 passed in 254.17s (0:04:14)` (`0` failed, `0` skipped).
- *(Note: `-p no:cacheprovider` used because Windows directory permissions on `.pytest_cache` were restricted in this workspace; `backend/.venv-harness` was used instead of `backend/.venv`, which emits a `~tarlette` invalid distribution warning.)*

### 3. Offline Evaluation Commands (No Code/Rubric Modifications)
All offline suites ran from `neo-trading-terminal/backend` using `.\.venv-harness\Scripts\python.exe`:

| Command | Dataset / Rubric | Mode | `model_evaluated` / Status | Observed Result | Exit |
|---|---|---|---|---|---|
| `python -m app.terminal.specialist_evals --mode offline` | `specialist-evals.v1` / `specialist-rubric.v1` | `offline` | `model_evaluated: False` | `18 passed / 18 total`, `0 failed` (`development: 9/9`, `held_out: 9/9`; `chain: 7/7`, `portfolio: 5/5`, `risk: 4/4`, `clarify: 2/2`; `routing: 3/3`, `numeric: 9/9`, `citation: 13/13`, `abstention: 18/18`) | `0` |
| `python -m app.terminal.options_evals --scope chain` | `options-evals.v1` / `chain-concepts.v1` | `offline` | `model_evaluated: False` | `6 passed / 6 total` | `0` |
| `python -m app.terminal.options_evals --scope portfolio` | `portfolio-evals.v1` / `portfolio-review.v1` | `offline` | `model_evaluated: False` | `11 passed / 11 total` | `0` |
| `python -m app.terminal.options_evals --scope portfolio-risk` | `portfolio-risk-evals.v1` / `portfolio-risk-explanation.v1` | `offline` | `model_evaluated: False` (`prompt_version: risk.1`, `calculation_version: portfolio-risk.1`) | `11 passed / 11 total` | `0` |
| `python -m app.terminal.options_platform_evals` | `options-platform-evals.1` / `options-platform-rubric.1` | `offline` | `offline_status: passed`, `model_quality: unverified` | `12 passed / 12 total`, `0 failed` | `0` |

**Offline vs. Live Boundary:** Offline evaluation passes confirm deterministic MCP transport, registry/projection isolation, routing validation, and arithmetic contracts only. They do **not** measure live LLM answer prose quality, local Ollama model availability/performance, or live Kotak broker responses.

### 4. Catch-All Agent & Factory Retirement Search
- **Command (from repo root):**
  `git grep -n -E "register_agent\('options_monitor'\)|\bbuild_agent\(" -- neo-trading-terminal/backend/app neo-trading-terminal/backend/tests neo-trading-terminal/frontend neo-trading-terminal/docs/OPTIONS_AGENT.md`
- **Result:** Exit code `1` (zero matches across `backend/app`, `backend/tests`, `frontend`, and `docs/OPTIONS_AGENT.md`).

### 5. Frontend Tests, Lint, Production Build, and Headless Browser Fixture Check
Executed from `neo-trading-terminal/frontend` on code commit `f93286b`:

| Command | Result | Exit |
|---|---|---|
| `npm.cmd test` (`node --test tests/*.test.cjs`) | `89 passed / 89 tests`, `0 failed`, `0 skipped` (includes `16` tests in `tests/specialist-agents.test.cjs` consuming all 5 frozen fixtures under `backend/evals/fixtures/specialist_api/*.json`, plus `17` tests in `tests/portfolioRisk.test.cjs` including frozen `risk.json` panel verification) | `0` |
| `npm.cmd run lint` (`eslint src`) | `0` errors, `0` warnings | `0` |
| `npm.cmd run build` (`next build --webpack`) | TypeScript passed (`3.6s`), compiled (`2.7s`), and statically exported all `15` pages including `/options-chat` | `0` |
| Ephemeral Headless Microsoft Edge (`playwright` `channel: 'msedge'`) against `frontend/out/options-chat` + local HTTP fixture mock server | `PLAYWRIGHT_EDGE_ROUND2_OK`: verified `snapshotError` alert renders as `DIV` with computed `span` color `rgb(252, 165, 165)`, Auto `portfolio -> 409 conversation_scope_changed` alert renders `span` color `rgb(252, 165, 165)`, and `pageErrors: []` *(in addition to Round 1 `c1ade55` Edge smoke checks)* | `0` |

---

## Independent Cross-Scope & Race-Condition Review Notes

1. **Late responses across specialist switches (`frontend/src/pages/options-chat.tsx`):**
   - `activeChatVersion` and `activeSnapshotVersion` refs replace the single shared `inFlight` flag, while `revision` increments on `changeMode`, `changeContext`, `startNewChat`, and `neodesk:session-expired`.
   - Switching specialist during an active request clears `busy` / `loadingSnapshot` immediately for the new mode, allows immediate submission in the new mode, and prevents late responses, late errors, or late `finally` cleanups from overwriting or unlocking the newer request.
2. **Auto-select clarification isolation & follow-up conversation preservation:**
   - `validateReply` handles `scope === 'clarify'` with `EXPECTED_AGENT_ID.clarify` (`master_router`), rejects spurious non-null `conversation_id` on an initial `clarify`, rejects embedded evidence fields, and preserves an active `conversation_id` when `clarify` occurs on a follow-up (preventing silent conversation resets and unflagged scope switches on the next turn). `resolvedScope` stays untouched, no evidence cards render, and monitoring/refresh stays disabled while `resolvedScope === null`.
3. **Portfolio analysis vs. portfolio risk isolation & contract hardening:**
   - `validateReply` enforces `EXPECTED_AGENT_ID` per scope (`options_trading_analysis`, `portfolio_analysis`, `portfolio_risk`), rejects `read_only === false`, blank `answer`, mid-conversation scope flips, partial/crash-prone `portfolio_snapshot` or `risk_snapshot.risk_report` payloads, mixed `risk_report`/`risk_report_ids`/`risk_inputs`/`risk_snapshot` inside `portfolio` responses (including `'risk_inputs' in ps`), and leaked `portfolio_snapshot` or account fields (`holdings`, `positions`, `funds`, `orders`, `sections`) inside `risk` responses.
   - `sanitizePortfolioSnapshot` strips `risk_report`/`risk_inputs` on manual `POST /options-agent/portfolio/snapshot` refreshes in `portfolio` mode.
   - Leaving `risk` (`changeMode` to non-`risk`, or `New chat` in `auto` mode) clears `policyRevision` so `<PortfolioRiskPanel>` cannot show stale policy-mismatch warnings before settings load, while `New chat` in explicit `risk` preserves `policyRevision` while `<PortfolioRiskSettings>` stays mounted.
4. **Market context, empty `Underlying`, error-alert contrast, and HTTP `409 conversation_scope_changed` handling:**
   - `changeContext` preserves typed composer `question` text when starting a new conversation. Clearing `Underlying` disables submit/suggestions in `chain` scope (avoiding guaranteed HTTP 422), while `auto` omits empty `context` so pre-routing portfolio/risk questions still succeed.
   - `api.ts` throws `ApiError` carrying `status === 409` and `code === 'conversation_scope_changed'`. `options-chat.tsx` keeps the draft and prior turns, stops monitoring, renders `<span>{error}</span>` inside `<div className="error options-chat-error" role="alert">` alongside `New chat`, never auto-resubmits, and resets only when clicked. `snapshotError` likewise renders inside `<div className="error options-chat-error" role="alert"><span>...</span></div>` so `globals.css` `p` rules cannot override `.error` contrast or margin.
   - `specialist-agents.test.cjs` executes loaded TypeScript modules in one shared `vm` context so `e instanceof Error` in `lib/api.ts:63` works accurately across `options-chat.tsx` and `lib/api.ts`, proving exact `validateReply` and `ApiError` error messages reach the UI alert rather than falling back to `'Request failed. Please try again.'`.
5. **Unverified surfaces in this environment:**
   - Live full-stack browser end-to-end execution against a live FastAPI server + real Kotak Neo broker session was not run.
   - Opt-in `--mode live-model` (OpenAI, Gemini, Ollama) and `--mode live-broker` evaluations were not executed because live provider credentials / Kotak session tokens are external to offline release checks; live model quality and Ollama availability remain unmeasured and deferred.
