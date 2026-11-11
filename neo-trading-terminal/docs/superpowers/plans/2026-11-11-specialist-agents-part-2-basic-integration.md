# Specialist Agents Part 2 — Basic Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use test-driven development for every behavior change and verification-before-completion before any completion claim. Steps use checkbox syntax for tracking.

**Goal:** Integrate the completed specialist-agent backend into the existing user interface, migrate remaining evaluation callers, update operational documentation, and run the full release verification without changing backend architecture or financial logic.

**Architecture:** Consume the frozen APIs, response models, error codes, and sanitized fixtures delivered by Part 1. Extend the existing options chat page with explicit specialist selection and Auto-select while reusing existing evidence/risk components and stale-response guards. Keep this phase bounded to UI wiring, fixture consumption, documentation, and verification.

**Tech stack:** Next.js/React/TypeScript frontend with existing CommonJS tests, existing Python evaluation commands, npm, pytest.

**Spec:** `docs/superpowers/plans/2026-11-11-specialist-agents.md`

**Required handoff:** `docs/superpowers/plans/SPECIALIST_AGENTS_HANDOFF.md` and `backend/evals/fixtures/specialist_api/*.json` from completed Part 1.

## Start condition for a separate coding interface

This plan may run in Codex, Antigravity, or another coding interface only after that interface opens the same repository state containing the completed Part 1 commit. Do not run it against the original pre-Part-1 codebase.

Before editing:

```powershell
git status --short
git log -1 --oneline
Test-Path docs/superpowers/plans/SPECIALIST_AGENTS_HANDOFF.md
Get-ChildItem backend/evals/fixtures/specialist_api
```

Read the handoff, the five fixtures, frontend `AGENTS.md`, current `options-chat.tsx`, existing frontend tests, and `docs/OPTIONS_AGENT.md`. If the handoff or fixtures are missing, stop and return the repository to Part 1.

## Global constraints

- Do not modify MCP authorization, capability scopes, agent contracts, provider adapters, harness limits, history isolation, deterministic calculations, or broker/session services.
- Do not recreate `options_monitor`, a generic factory, or a compatibility fallback.
- Do not invent or reinterpret request/response fields. A contract mismatch is a Part 1 defect.
- One user submission may create at most one specialist request.
- Clarification displays no evidence and creates no specialist conversation.
- A scope-change response must preserve typed text, offer a new chat, and never automatically resubmit.
- Ollama, memory, strategy agents, order execution, and new formulas remain deferred.

## Review focus

- Late responses from a previous scope must not render after a user changes specialist.
- Auto clarification must not be rendered as an empty specialist result or attach stale evidence.
- Risk responses must use the existing risk presentation; portfolio analysis must not show risk findings.
- A `conversation_scope_changed` response must not discard the user's draft or silently retry.
- Offline fixture/evaluation results must not be described as live-model quality.

## Frozen interface map

| UI choice | Agent ID | Endpoint/flow | Renderer |
|---|---|---|---|
| Options and trading | `options_trading_analysis` | existing chain/report chat | existing chain/report evidence |
| Portfolio analysis | `portfolio_analysis` | portfolio analysis chat from Part 1 handoff | existing `PortfolioEvidence` behavior |
| Portfolio risk | `portfolio_risk` | risk chat from Part 1 handoff | existing `RiskPanel` behavior |
| Auto-select | returned by `master_router` | existing unified chat | renderer selected by returned scope |

The Part 1 handoff overrides endpoint details if this table and the implemented API differ.

## Dependency order

```text
Task 1 contract tests → Task 2 explicit specialist UI → Task 3 Auto/follow-ups
                                                   → Task 4 docs/eval confirmation
                                                   → Task 5 full release verification
```

Execute this document as two fresh-context subplans:

| Subplan | Wave | Depends on | Tasks |
|---|---:|---|---|
| B1 Frontend integration | 1 | completed Part 1 | 1–3 |
| B2 Migration and release | 2 | B1 | 4–5 |

---

## Subplan B1 — Frontend integration

### Task 1: Pin frontend behavior to frozen Part 1 fixtures

**Files:**
- Create: `frontend/tests/specialist-agents.test.cjs`
- Read: `backend/evals/fixtures/specialist_api/chain.json`
- Read: `backend/evals/fixtures/specialist_api/portfolio.json`
- Read: `backend/evals/fixtures/specialist_api/risk.json`
- Read: `backend/evals/fixtures/specialist_api/clarify.json`
- Read: `backend/evals/fixtures/specialist_api/scope_change.json`

**Interfaces:**
- Consumes: frozen Part 1 API fixture fields and error codes.
- Produces: frontend regression tests for all explicit/Auto states before implementation.

**Action:** Extend the repository's existing frontend test style. Mock the actual endpoint paths from the handoff. Assert request payloads, returned `agent_id`/scope handling, evidence renderer selection, clarification with no evidence, scope-change draft preservation, and stale-response suppression. Do not duplicate backend schema logic in frontend code; fixtures are the contract boundary.

- [ ] Add one failing test for each explicit specialist.
- [ ] Add failing tests for Auto chain/portfolio/risk/clarify.
- [ ] Add failing tests for scope change, user switching during a pending request, and late response suppression.
- [ ] Run the targeted suite and confirm failures are caused by missing UI wiring.

**Verify:** `npm test -- specialist-agents.test.cjs` from `frontend`

**Done:** tests pin every user-visible state and consume only sanitized frozen fixtures.

---

### Task 2: Add explicit specialist selection and rendering

**Files:**
- Modify: `frontend/src/pages/options-chat.tsx`
- Modify: `frontend/tests/specialist-agents.test.cjs`
- Modify: `frontend/tests/portfolioRisk.test.cjs`

**Interfaces:**
- Consumes: explicit endpoint map and fixtures from Task 1.
- Produces: selectable Options and trading, Portfolio analysis, and Portfolio risk modes.

**Action:** Add the three choices using existing page patterns. Options/trading retains current chain/report display. Portfolio analysis calls its frozen endpoint and renders the existing portfolio evidence view. Portfolio risk calls its frozen endpoint and renders existing `RiskPanel` behavior. When a user switches mode, invalidate the pending request/revision and begin a new compatible conversation. Do not change shared backend types or financial formatting unless an existing frontend test requires it.

- [ ] Run Task 1 tests and confirm RED.
- [ ] Implement mode state, endpoint selection, request payload, and matching render branches.
- [ ] Add/adjust accessibility labels and disabled/loading behavior using current UI conventions.
- [ ] Run targeted tests and confirm PASS.

**Verify:** `npm test -- specialist-agents.test.cjs portfolioRisk.test.cjs`

**Done:** every explicit choice calls exactly one matching endpoint and renders only its matching evidence contract.

---

### Task 3: Add Auto-select, clarification, and safe follow-ups

**Files:**
- Modify: `frontend/src/pages/options-chat.tsx`
- Modify: `frontend/tests/specialist-agents.test.cjs`
- Read: `frontend/src/lib/api.ts` (`ApiError.status`, `ApiError.code`, and structured error messages are implemented by audit remediation).

**Interfaces:**
- Consumes: unified chat response scope/agent fields and `conversation_scope_changed` behavior from Part 1.
- Produces: Auto mode that renders chain, portfolio, risk, or clarification safely.

**Action:** Add Auto-select as the default or additional choice according to the existing page convention. Call unified chat once per submission and branch on validated returned scope. Show returned agent/scope metadata. Clarification contains text only and no evidence. Disable periodic evidence refresh until a concrete scope exists. For HTTP 409 `conversation_scope_changed`, keep the draft, display a New chat action, clear incompatible conversation state only after user confirmation, and do not resubmit automatically. Preserve existing revision/abort guards so late replies cannot render under another scope.

- [ ] Confirm Auto and race-condition tests are RED.
- [ ] Implement one-request Auto flow and scope-specific render selection.
- [ ] Implement clarification and explicit scope-change UI.
- [ ] Confirm pending-switch and late-response tests PASS.

**Verify:** `npm test -- specialist-agents.test.cjs portfolioRisk.test.cjs`

**Done:** Auto reaches one visible specialist or clarification, follow-ups stay safe, and stale results never cross scopes.

---

## Subplan B2 — Documentation and release verification

### Task 4: Confirm evaluations and update documentation

**Files:**
- Modify: `docs/OPTIONS_AGENT.md`

**Interfaces:**
- Consumes: completed Part 1 evaluation CLIs and handoff documentation.
- Produces: updated operator/developer documentation and evidence that legacy evaluation callers are already retired.

**Action:** Run the existing options, portfolio, risk, and specialist offline evaluations delivered by Part 1. Do not change evaluator code, scoring, rubric semantics, authorization, or agent contracts; return any failure requiring such a change to Part 1. Update documentation with agent mapping, explicit/Auto flows, risk endpoint, history restart behavior, error handling, limits, trace interpretation, offline-vs-live evaluation distinction, and Ollama deferral.

- [ ] Run the catch-all search and confirm Part 1 left no active registration/caller.
- [ ] Run all documented offline evaluation commands without editing their implementation.
- [ ] Update documentation to match the implemented handoff exactly.
- [ ] Re-run the frontend targeted tests after documentation-linked labels/examples are finalized.

**Verify:** `python -m app.terminal.specialist_evals --mode offline` plus the repository's existing options/options-platform evaluation commands; `rg "register_agent\('options_monitor'\)|\bbuild_agent\(" backend/app backend/tests` must return no active catch-all references.

**Done:** Part 1 evaluations remain green and documentation describes actual behavior without claiming Ollama or live quality work is complete.

---

### Task 5: Execute release verification and close only bounded defects

**Files:**
- Modify: only files already owned by Tasks 1–4 when a failing test proves a bounded integration defect.
- Create: `docs/superpowers/plans/SPECIALIST_AGENTS_PART_2_VERIFICATION.md`

**Interfaces:**
- Consumes: completed Part 1 plus Tasks 1–4.
- Produces: evidence-backed verification record with commands, results, failures, and final commit SHA.

**Action:** Run full backend and frontend gates. Fix only UI wiring, fixture-consumption, or documentation defects. If a failure requires changing backend evaluation code, security boundaries, contracts, harnesses, histories, provider accounting, or finance logic, record it as a Part 1 blocker and stop instead of expanding scope. Run a final independent review focused on cross-scope UI state and obsolete catch-all usage.

- [ ] Run backend dependency, full pytest, offline evaluations, and catch-all search.
- [ ] Run frontend tests, lint, and production build.
- [ ] Record exact commands, counts, failures, and whether failures pre-existed.
- [ ] Resolve bounded Critical/Important findings with a failing test first.

**Verify:** all commands under Final verification complete successfully, or an out-of-scope Part 1 blocker is documented without a false completion claim.

**Done:** release gates pass, no active catch-all remains, and the verification record accurately describes the tested repository state.

## Final verification

From `backend`:

```powershell
python -m pip check
python -m pytest
python -m app.terminal.specialist_evals --mode offline
rg "register_agent\('options_monitor'\)|\bbuild_agent\(" app tests
```

Run all existing options and options-platform evaluation commands documented in the repository. Live-provider evaluation remains explicit opt-in.

From `frontend`:

```powershell
npm test
npm run lint
npm run build
```

## Success criteria

- Explicit Options/trading, Portfolio analysis, and Portfolio risk modes work against frozen Part 1 APIs.
- Auto-select safely renders chain, portfolio, risk, or clarification from one request.
- Conversation scope changes and late responses cannot mix histories or evidence.
- Remaining evaluation callers and docs contain no catch-all dependency.
- Full backend/frontend checks pass, or a genuine Part 1 blocker is isolated and reported without unauthorized architectural edits.

