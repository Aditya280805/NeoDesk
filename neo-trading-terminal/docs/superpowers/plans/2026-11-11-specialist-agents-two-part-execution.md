# Specialist Agents — Two-Part Execution Split

**Source plan:** `docs/superpowers/plans/2026-11-11-specialist-agents.md`

**Purpose:** Divide implementation by reasoning difficulty and failure risk. Part 1 owns architecture and security-sensitive behavior. Part 2 receives frozen contracts and performs bounded product integration, migration, documentation, and release execution.

**Order:** Part 1 must finish and pass its handoff gate before Part 2 begins. The two parts are not safe to run in parallel because Part 2 consumes APIs, contracts, error codes, and UI payloads established by Part 1.

## Part 1 — Heavy lifting: secure multi-agent core

**Recommended executor:** strongest available coding/reasoning model with a fresh context window.

**Why this is difficult:** This work changes trust boundaries, request lifecycles, provider accounting, history isolation, and runtime dispatch. A locally correct change can still create cross-agent data leakage, reset budgets during delegation, persist invalid output, or route a conversation under the wrong owner/scope.

### Included source-plan work

| Source task | Work owned by Part 1 |
|---|---|
| 01.1 | Define agent/scope mappings, strict response contracts, prompt versions, and fail-closed validation. |
| 01.2 | Implement and register fresh specialist factories; preserve the old factory only until caller migration. |
| 02.1 | Build detached portfolio-analysis and portfolio-risk MCP projections over one private evidence acquisition. |
| 02.2 | Enforce and prove the complete server-side tool authorization matrix. |
| 03.1 | Implement cumulative deadlines, attempts, token/context limits, request-local state, and provider-boundary accounting. |
| 03.2 | Integrate Gemini accounting, sanitized traces, stable failure codes, cancellation, and stage timings. |
| 04.1 | Migrate explicit APIs to specialists, add risk chat, isolate history, validate citations, publish atomically, and remove the catch-all. |
| 04.2 | Implement the tool-less master router, sticky follow-ups, clarification, topic-change handling, and parent/child metrics. |
| 06.1 core | Define the versioned evaluation schema, reference cases, expected routes/tools/citations/numbers, and offline evaluator behavior. |

### Exact file ownership

- `backend/app/terminal/agent_scope.py`
- `backend/app/terminal/agent_registry.py`
- `backend/app/terminal/specialist_agents.py`
- `backend/app/terminal/options_mcp.py`
- `backend/app/terminal/agent_harness.py`
- `backend/app/terminal/options_model.py`
- `backend/app/terminal/options_gemini.py`
- `backend/app/core/config.py`
- `backend/app/terminal/options_agent.py`
- `backend/app/terminal/routers/options_agent.py`
- `backend/app/terminal/unified_chat.py`
- `backend/app/terminal/specialist_evals.py`
- `backend/evals/specialist_cases.json`
- `backend/evals/specialist_rubric.json`
- Corresponding backend tests named in source Plans 01–04 and Task 06.1.

### Execution sequence

1. Implement source Plan 01 using tests first.
2. Implement source Plans 02 and 03. They may be separate fresh-context runs, but Plan 03 must not assume access to broad evidence.
3. Implement source Plan 04 only after Plans 02 and 03 pass.
4. Implement the Task 06.1 evaluation schema and offline harness against the actual production factories and validators.
5. Run the Part 1 handoff gate and produce a short handoff record containing final endpoint schemas, agent IDs, scopes, failure codes, and test results.

### Part 1 verification

Run from `backend`:

```powershell
python -m pytest tests/test_specialist_agents.py tests/test_specialist_mcp.py tests/test_portfolio_mcp.py tests/test_options_mcp.py -q
python -m pytest tests/test_agent_harness.py tests/test_agent_harness_traces.py tests/test_options_model.py tests/test_options_gemini.py tests/test_key_rotator.py -q
python -m pytest tests/test_specialist_api.py tests/test_portfolio_agent.py tests/test_options_agent.py tests/test_options_report_chat.py tests/test_unified_routing.py -q
python -m pytest tests/test_specialist_evals.py -q
python -m app.terminal.specialist_evals --mode offline
rg "register_agent\('options_monitor'\)|\bbuild_agent\(" app tests
```

The final `rg` command must return no active catch-all implementation or caller.

### Part 1 done criteria

- Three fresh specialists exist and each accepts only its allowed scope/tool/contract combination.
- Master/router has no private capability and cannot answer financial questions itself.
- Analysis cannot see risk findings; risk cannot see account rows; unauthorized tool discovery and invocation fail server-side.
- Explicit and Auto requests share non-resettable parent budgets and deadlines.
- History is isolated by owner, agent, scope, contract, and selected context.
- Invalid schema/citations, stale sessions, cancellation, or provider failures never publish a successful turn.
- The old `options_monitor` factory and active `build_agent` call path are removed only after all callers migrate.
- Offline evaluation cases run through production factories/projections/validators.

## Mandatory handoff from Part 1 to Part 2

Part 2 may start only when all boxes below are satisfied:

- [ ] Final agent IDs are `options_trading_analysis`, `portfolio_analysis`, and `portfolio_risk`.
- [ ] Final Auto scopes are `chain`, `portfolio`, `risk`, and `clarify`.
- [ ] Risk endpoint and response fields are frozen and documented in the handoff record.
- [ ] Analysis, risk, chain, report, clarification, and scope-change fixture responses are available for frontend tests.
- [ ] `conversation_scope_changed` behavior is frozen, including HTTP status and safe user action.
- [ ] Evidence IDs, risk-report IDs, `agent_id`, `parent_run_id`, and `read_only` semantics are frozen.
- [ ] Targeted Part 1 test suites pass.
- [ ] No unresolved Critical or Important security/correctness finding remains.

If any item is missing, return the work to Part 1 instead of letting Part 2 invent a contract.

## Part 2 — Bounded implementation: UI, migration, docs, and release checks

**Recommended executor:** simpler/cheaper coding model, using only the source plan, Part 1 handoff record, relevant frontend instructions, and files listed below.

**Why this is bounded:** The executor consumes frozen endpoints and fixtures. It does not choose the architecture, alter authorization, change financial calculations, widen tools, redesign the harness, or reinterpret response contracts.

### Included source-plan work

| Source task | Work owned by Part 2 |
|---|---|
| 05.1 | Add the three explicit specialist choices and render their frozen response contracts with existing components. |
| 05.2 | Add Auto-select, clarification, safe scope changes, pending-request invalidation, and stale-reply guards. |
| 06.1 fixtures | Expand only data fixtures/cases already defined by Part 1; do not change evaluator semantics or acceptance rules. |
| 06.2 | Migrate remaining evaluation callers, update documentation, execute complete verification, and report pre-existing failures accurately. |

### Exact file ownership

- `frontend/src/pages/options-chat.tsx`
- `frontend/tests/specialist-agents.test.cjs`
- `frontend/tests/portfolioRisk.test.cjs`
- `backend/app/terminal/options_evals.py`
- Evaluation tests discovered by the bounded catch-all search in Task 06.2.
- `docs/OPTIONS_AGENT.md`
- Existing evaluation JSON files only for adding Part 1-specified cases; no schema or rubric changes without returning to Part 1.

### Guardrails for the simpler executor

- Do not modify MCP authorization, capability creation, agent contracts, provider adapters, harness limits, history isolation, or deterministic finance logic.
- Do not add compatibility fallbacks to `options_monitor` or recreate a generic factory.
- Do not infer missing API fields. Stop and return a contract gap to Part 1.
- Do not send more than one specialist request for one user submission.
- Do not render evidence for `clarify` or automatically resubmit after a scope-change response.
- Preserve typed text when offering a new chat; invalidate late responses after agent/scope changes.
- Keep offline/mock evaluation results separate from live-model quality claims.

### Part 2 verification

Run from `frontend`:

```powershell
npm test -- specialist-agents.test.cjs portfolioRisk.test.cjs
npm test
npm run lint
npm run build
```

Run from `backend`:

```powershell
python -m pip check
python -m pytest
python -m app.terminal.specialist_evals --mode offline
rg "register_agent\('options_monitor'\)|\bbuild_agent\(" app tests
```

Run every existing options/options-platform evaluation command documented by the repository. Live-provider runs remain explicit opt-in.

### Part 2 done criteria

- Users can explicitly select each specialist or use Auto-select.
- Every UI mode calls and renders only its matching frozen contract.
- Clarification, scope changes, pending cancellation, and stale responses behave safely.
- Remaining tests/evaluations use registered specialists and projections, with no catch-all fallback.
- Documentation reflects the implemented mapping, endpoint behavior, history restart, limits, and Ollama deferral.
- Backend tests, frontend tests, lint, build, offline evaluations, and catch-all searches pass, or pre-existing failures are recorded with evidence.

## Final dependency view

```text
PART 1 — HEAVY CORE
  Contracts/factories
      → MCP security boundaries
      → harness budgets/tracing
      → runtime + master router
      → evaluation contract
      → HANDOFF GATE

PART 2 — BOUNDED INTEGRATION
  UI specialist modes + Auto-select
      → evaluation-call migration
      → documentation
      → full release verification
```

## Effort split

- **Part 1:** approximately 75–80% of implementation risk and 65–75% of coding effort.
- **Part 2:** approximately 20–25% of implementation risk and 25–35% of coding effort.

Use fresh context for each major Part 1 subsystem. Part 2 can be completed in one focused execution only if the handoff record is complete; otherwise split UI and release verification into separate runs.
