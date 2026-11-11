# Specialist Agents Part 2 — Verification Record

## Repository & Baseline State

- **Branch:** `codex/local-specialist-agents`
- **Base Commit (`HEAD`):** `0047dc4 docs(specialist-agents): update Part 1 handoff and progress with code-fix SHA`
- **Working Tree Composition (uncommitted):**
  - **Pre-existing Part 1 debug-audit remediation present prior to Part 2 edits:** `backend/app/terminal/{agent_harness.py,agent_scope.py,options_agent.py,options_mcp.py,unified_chat.py}`, `backend/tests/{test_portfolio_agent.py,test_portfolio_risk_integration.py,test_specialist_mcp.py,test_audit_regressions.py}`, `frontend/src/lib/api.ts`, `frontend/tests/session.test.cjs`, `docs/superpowers/plans/{2026-11-11-specialist-agents-part-2-basic-integration.md,2026-11-11-specialist-agents-debug-audit.md}`. No Part 2 edits modified backend contracts, MCP authorization, harness limits, history isolation, or deterministic finance calculations.
  - **Part 2 integration & documentation changes:**
    - Modified: `frontend/src/pages/options-chat.tsx`
    - Modified: `frontend/tests/portfolioRisk.test.cjs`
    - Created: `frontend/tests/specialist-agents.test.cjs`
    - Modified: `docs/OPTIONS_AGENT.md`
    - Created: `docs/superpowers/plans/SPECIALIST_AGENTS_PART_2_VERIFICATION.md`

---

## Executed Verification Commands & Observed Results

### 1. Backend Dependency Integrity (`pip check`)
- **Command (from `neo-trading-terminal`):**
  `.\backend\.venv-harness\Scripts\python.exe -m pip check`
- **Result:** Exit code `0` — `No broken requirements found.`

### 2. Backend Full Pytest Suite
- **Command (from `neo-trading-terminal/backend`):**
  `.\.venv-harness\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`
- **Result:** Exit code `0` — `658 passed in 316.03s (0:05:16)` (`0` failed, `0` skipped).
- *(Note: `-p no:cacheprovider` used because Windows directory permissions on `.pytest_cache` were restricted in this workspace; `backend/.venv-harness` was used instead of `backend/.venv`, which emits a `~tarlette` invalid distribution warning).*

### 3. Offline Evaluation Commands (No Code/Rubric Modifications)
All offline suites ran from `neo-trading-terminal/backend` using `.\.venv-harness\Scripts\python.exe`:

| Command | Dataset / Rubric | Mode | `model_evaluated` | Observed Result | Exit |
|---|---|---|---|---|---|
| `python -m app.terminal.specialist_evals --mode offline` | `specialist-evals.v1` / `specialist-rubric.v1` | `offline` | `False` | `18 passed / 18 total`, `0 failed` (`development: 9/9`, `held_out: 9/9`; `chain: 7/7`, `portfolio: 5/5`, `risk: 4/4`, `clarify: 2/2`; `routing: 3/3`, `numeric: 9/9`, `citation: 13/13`, `abstention: 18/18`) | `0` |
| `python -m app.terminal.options_evals --scope chain` | `options-evals.v1` / `chain-concepts.v1` | `offline` | `False` | `6 passed / 6 total` | `0` |
| `python -m app.terminal.options_evals --scope portfolio` | `portfolio-evals.v1` / `portfolio-review.v1` | `offline` | `False` | `11 passed / 11 total` | `0` |
| `python -m app.terminal.options_evals --scope portfolio-risk` | `portfolio-risk-evals.v1` / `portfolio-risk-explanation.v1` | `offline` | `False` | `11 passed / 11 total` | `0` |
| `python -m app.terminal.options_platform_evals` | `options-platform-evals.1` / `options-platform-rubric.1` | `offline` | `False` (n/a offline) | `12 passed / 12 total`, `0 failed` | `0` |

**Offline vs. Live Boundary:** Offline evaluation passes confirm deterministic MCP transport, registry/projection isolation, routing validation, and arithmetic contracts only. They do **not** measure live LLM answer prose quality, local Ollama model availability/performance, or live Kotak broker responses.

### 4. Catch-All Agent & Factory Retirement Search
- **Command (from `neo-trading-terminal`):**
  `git grep -n -E "register_agent\('options_monitor'\)|\bbuild_agent\(" -- backend/app backend/tests`
- **Result:** Exit code `1` (zero matches in `backend/app` and `backend/tests`).
- **Additional check:**
  - `git grep -n "options_monitor" -- backend/app backend/tests frontend/src` matched only unrelated platform monitoring service files (`options_monitoring*.py`, `server.py`) and negative test assertions (`backend/tests/test_specialist_evals.py:173,179` confirming `'options_monitor' not in list_agents()`).
  - `git grep -n -E "options_monitor|build_agent|get_portfolio_snapshot" -- docs/OPTIONS_AGENT.md frontend/src` matched only `docs/OPTIONS_AGENT.md:126` noting `options_monitor` and `build_agent` are retired (`0` matches in `frontend/src`).

### 5. Frontend Tests, Lint, and Production Build
Executed from `neo-trading-terminal/frontend` after all code and documentation edits:

| Command | Result | Exit |
|---|---|---|
| `npm.cmd test` (`node --test tests/*.test.cjs`) | `83 passed / 83 tests`, `0 failed`, `0 skipped` (includes `10` new tests in `tests/specialist-agents.test.cjs` consuming all 5 frozen fixtures under `backend/evals/fixtures/specialist_api/*.json`, plus `17` tests in `tests/portfolioRisk.test.cjs` including frozen `risk.json` panel verification) | `0` |
| `npm.cmd run lint` (`eslint src`) | `0` errors, `0` warnings | `0` |
| `npm.cmd run build` (`next build --webpack`) | TypeScript passed (`4.0s`), compiled and statically exported all `15` pages including `/options-chat` | `0` |

---

## Independent Cross-Scope & Race-Condition Review Notes

1. **Late responses across specialist switches (`frontend/src/pages/options-chat.tsx`):**
   - `activeChatVersion` and `activeSnapshotVersion` refs replace the single shared `inFlight` flag, while `revision` increments on `changeMode`, `changeContext`, `startNewChat`, and `neodesk:session-expired`.
   - Switching specialist during an active request clears `busy` / `loadingSnapshot` immediately for the new mode, allows immediate submission in the new mode, and prevents late responses, late errors, or late `finally` cleanups from overwriting or unlocking the newer request.
2. **Auto-select clarification isolation:**
   - `validateReply` handles `scope === 'clarify'` with `conversation_id: null`. `ask()` sets `conversationId` to `null`, keeps `resolvedScope` `null`, omits `.options-evidence`, and keeps `Refresh snapshot` and `Refresh every minute` disabled (`refreshDisabled === true`).
3. **Portfolio analysis vs. portfolio risk isolation:**
   - Explicit `portfolio` and Auto-routed `portfolio` render only `<PortfolioEvidence />` (no `PortfolioRiskPanel`, no `PortfolioRiskSettings`).
   - Explicit `risk` and Auto-routed `risk` render only `<PortfolioRiskPanel />` and `<PortfolioRiskSettings />` (no `<PortfolioEvidence />`, no account rows). Snapshot refresh under `risk` stores only `{ evidence_id, risk_report }` into `riskSnapshot`.
4. **HTTP `409 conversation_scope_changed` handling:**
   - `api.ts` throws `ApiError` carrying `status === 409` and `code === 'conversation_scope_changed'`. `options-chat.tsx` preserves the textarea draft (`question`) and prior turns, stops monitoring, displays the server message plus a `New chat` button inside `role="alert"`, never auto-resubmits, and resets conversation state only when the user clicks `New chat`.
5. **Unverified surfaces in this environment:**
   - Live browser end-to-end execution (DOM event wiring with live Chromium + Next static bundle against running FastAPI + Kotak REST) was not run.
   - Opt-in `--mode live-model` (OpenAI, Gemini, Ollama) and `--mode live-broker` evaluations were not executed because live provider credentials / Kotak session tokens are external to offline release checks; live model quality and Ollama availability remain unmeasured and deferred.
