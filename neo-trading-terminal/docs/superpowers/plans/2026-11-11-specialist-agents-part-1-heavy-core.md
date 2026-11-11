# Specialist Agents Part 1 — Heavy Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Use test-driven development for every behavior change and verification-before-completion before any completion claim. Steps use checkbox syntax for tracking.

**Goal:** Replace the catch-all backend agent with three secure specialist agents and one tool-less master router, backed by server-enforced evidence boundaries, isolated histories, cumulative request budgets, sanitized traces, and an offline evaluation harness.

**Architecture:** Keep the current FastAPI runner, private FastMCP transport, deterministic portfolio/risk calculations, data services, SQLite stores, and Agno 3.1.10. Trusted backend code creates one request-scoped capability and one fresh specialist per request; the master only classifies. All nested work shares one parent harness for deadlines, model attempts, tool calls, context limits, and traces.

**Tech stack:** Python, FastAPI, Pydantic, Agno 3.1.10, FastMCP, pytest, SQLite, local Ollama inference. User override: Ollama is now required; preserve provider-independent accounting and prohibit cloud fallback for local requests. Existing cloud adapters remain compatibility paths until migration decisions are verified.

**Spec:** `docs/superpowers/plans/2026-11-11-specialist-agents.md`

**Output consumed by Part 2:** implemented backend plus `docs/superpowers/plans/SPECIALIST_AGENTS_HANDOFF.md` and frozen JSON fixtures under `backend/evals/fixtures/specialist_api/`.

## Global constraints

- Preserve existing calculations, broker/session access, option/portfolio snapshots, saved-report explanations, historical reads, and read-only behavior.
- Agents may not place orders, change policies, create jobs, or introduce new financial formulas.
- Keep the legacy `get_portfolio_snapshot` for non-agent consumers, but expose it to no specialist.
- Explicit selection bypasses the master. Saved-report explanations bypass classification.
- The master/router owns no private MCP capability and receives no evidence or previous assistant answers.
- Fail closed on unknown agent/scope/tool/contract combinations.
- Do not delete `options_monitor` until every production and evaluation caller has migrated and targeted tests pass.
- Do not change frontend files in Part 1.

## Review focus

- Cross-user conversation IDs must fail before evidence acquisition.
- Analysis must never receive risk findings; risk must never receive holdings, positions, funds, or orders.
- Retry/key rotation and nested routing must not reset parent attempts, tool limits, or deadlines.
- Topic changes and legacy mixed conversations must return `conversation_scope_changed` before fetching evidence.
- Invalid schemas, forged citations, cancellation, stale sessions, and provider errors must never persist a successful turn.

## Required target contracts

| Agent ID | Scope | Private tool | Output |
|---|---|---|---|
| `options_trading_analysis` | `chain` plus selected saved-report scopes | `get_option_snapshot` or exactly one selected report tool | existing `AgentAnswer` / `ReportAnswer` |
| `portfolio_analysis` | `portfolio` | `get_portfolio_analysis_snapshot` | `PortfolioAnalysisAnswer` |
| `portfolio_risk` | `risk` | `get_portfolio_risk_report` | `PortfolioRiskAnswer` |
| `master_router` | `chain | portfolio | risk | clarify` | none | `RouteAnswer` |

## Dependency order

```text
Task 1 contracts → Task 2 factories → Task 3 MCP projections → Task 4 authorization
                                             ↘
Task 5 harness → Task 6 adapters/traces ──────→ Task 7 explicit runtime
                                                   → Task 8 master router/history
                                                   → Task 9 evaluations
                                                   → Task 10 fixtures/handoff
```

Execute this document as four fresh-context subplans:

| Subplan | Wave | Depends on | Tasks |
|---|---:|---|---|
| H1 Contracts and factories | 1 | — | 1–2 |
| H2 Evidence security | 2 | H1 | 3–4 |
| H3 Harness and traces | 2 | H1 | 5–6 |
| H4 Runtime and router | 3 | H2, H3 | 7–8 |
| H5 Evaluations and handoff | 4 | H4 | 9–10 |

---

## Subplan H1 — Contracts and factories

### Task 1: Define specialist scopes and strict response contracts

**Files:**
- Modify: `backend/app/terminal/agent_scope.py`
- Create: `backend/tests/test_specialist_agents.py`

**Interfaces:**
- Produces: scope metadata carrying `agent_id`, scope, contract version, instructions, authorized tool name, and response model.
- Produces: strict `PortfolioAnalysisAnswer`, `PortfolioRiskAnswer`, and `RouteAnswer` Pydantic models.

**Action:** Add failing tests for every supported mapping and invalid pairing. Split mixed portfolio instructions into analysis and risk instructions. Use contract versions `analysis.1` and `risk.1`. `PortfolioAnalysisAnswer` must contain a non-empty answer and exactly one UUID evidence ID, forbid extra fields, and reject risk citations. `PortfolioRiskAnswer` must contain a non-empty answer, exactly one UUID evidence ID and one risk-report ID, and forbid extras. `RouteAnswer` must accept only `chain`, `portfolio`, `risk`, or `clarify`. Keep calculations out of prompts.

- [ ] Write mapping, schema, extra-field, empty-answer, malformed-UUID, and wrong-agent/scope tests.
- [ ] Run `python -m pytest tests/test_specialist_agents.py -q` from `backend`; confirm RED for missing contracts.
- [ ] Implement the minimal contracts and mappings.
- [ ] Re-run the test; confirm PASS.

**Verify:** `python -m pytest tests/test_specialist_agents.py -q`

**Done:** every supported scope resolves to exactly one agent, contract, prompt version, and authorized tool; all unknown combinations fail closed.

---

### Task 2: Register fresh specialist factories

**Files:**
- Create: `backend/app/terminal/specialist_agents.py`
- Modify: `backend/app/terminal/agent_registry.py`
- Modify: `backend/tests/test_specialist_agents.py`

**Interfaces:**
- Consumes: Task 1 scope metadata and response models.
- Produces: registered fresh factories for `options_trading_analysis`, `portfolio_analysis`, and `portfolio_risk` with signature `(config, snapshot, tools, *, scope) -> Agent`.

**Action:** Test first. Each factory validates that its scope belongs to the factory, creates a fresh model and Agno Agent, receives only the already-filtered tool list, applies the exact response schema, and stores no live singleton. Widen registry typing only enough to support a later Team factory. Retain the old factory temporarily for caller migration; do not use it in new tests.

- [ ] Add tests for registry resolution, fresh identity, exact tool list, schema selection, generation settings, and wrong-scope rejection.
- [ ] Run the targeted test and confirm RED.
- [ ] Implement factories and registry typing.
- [ ] Re-run and confirm PASS.

**Verify:** `python -m pytest tests/test_specialist_agents.py -q`

**Done:** the registry resolves three independent non-catch-all specialists and no factory accepts another specialist's scope.

---

## Subplan H2 — Evidence security

### Task 3: Build detached private evidence projections

**Files:**
- Modify: `backend/app/terminal/options_mcp.py`
- Create: `backend/tests/test_specialist_mcp.py`

**Interfaces:**
- Consumes: existing portfolio acquisition and deterministic risk evaluation.
- Produces: `get_portfolio_analysis_snapshot` returning a detached validated `PortfolioSnapshot` projection without risk.
- Produces: `get_portfolio_risk_report` returning only `{evidence_id, risk_report}` with matching IDs and no account rows.

**Action:** Add analysis/risk capability scopes and tools. Acquire portfolio evidence and calculate risk once, retain the full envelope only in private request state, and return detached copies. Apply existing owner, session, policy, origin, generation, deadline, cancellation, cache, and tool-budget checks. Do not expose a broad envelope accessor through MCP connections, tools, prompts, logs, or model context.

- [ ] Test exact projection fields, matching IDs, one acquisition, immutable repeated reads, stale session, cancellation, deadline, and cache behavior.
- [ ] Confirm the tests fail before implementation.
- [ ] Implement the scopes, projections, and private envelope lifecycle.
- [ ] Confirm all targeted MCP tests pass.

**Verify:** `python -m pytest tests/test_specialist_mcp.py -q`

**Done:** analysis and risk receive minimum necessary evidence from one private acquisition without a model-visible broad handle.

---

### Task 4: Prove the server-side authorization matrix

**Files:**
- Modify: `backend/tests/test_specialist_mcp.py`
- Modify: `backend/tests/test_portfolio_mcp.py`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: Task 3 capability scopes and tool registrations.
- Produces: exhaustive permission tests for chain, analysis, risk, and all existing saved-report scopes.

**Action:** Parameterize every capability against every private tool, including legacy portfolio. Test both discovery and direct invocation, correct/incorrect arguments, expiry, revocation, origin rejection, owner/session mismatch, and a router with no capability. Update the engineering boundary in `AGENTS.md`. Do not rely on prompt wording for authorization.

- [ ] Write the full allow/deny matrix and assert exactly one visible tool per specialist capability.
- [ ] Run it and confirm intended failures expose missing enforcement.
- [ ] Tighten server filtering/invocation checks only where tests demonstrate a gap.
- [ ] Run all MCP suites.

**Verify:** `python -m pytest tests/test_specialist_mcp.py tests/test_portfolio_mcp.py tests/test_options_mcp.py -q`

**Done:** unauthorized discovery and invocation are impossible through normal clients or direct protocol calls.

---

## Subplan H3 — Harness and traces

### Task 5: Implement the cumulative request harness

**Files:**
- Create: `backend/app/terminal/agent_harness.py`
- Create: `backend/tests/test_agent_harness.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/terminal/options_model.py`

**Interfaces:**
- Produces: request-local parent/stage budget context, reserve/account hooks, deadline checks, context estimation/trimming, and stable harness failure codes.
- Required values: explicit deadline 60 seconds; Auto deadline 85 seconds; router attempts 3; specialist attempts 3; Auto total 6; model-requested specialist tools 2; private reads 3 including prefetch; input estimate 24,000 tokens; context limit 32,768; existing 65,536-byte prompt ceiling.

**Action:** Use ContextVar-backed state so sibling requests isolate correctly while child stages share one parent. Block the next provider/tool call before limits are exceeded. Missing usage reserves the full requested allowance; reported usage replaces reservations according to existing adapter semantics. Estimate complete provider input and trim only oldest compatible history, never required IDs, freshness/missing states, findings, or limitations. Preserve existing concurrency and per-user admission limits.

- [ ] Test sibling isolation, nested non-reset, retry/key rotation, unknown usage, expired deadlines, tool limits, oversized input, and protected evidence fields.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement validated settings and harness primitives.
- [ ] Integrate OpenAI/provider-boundary accounting in `options_model.py`.
- [ ] Re-run targeted tests and confirm PASS.

**Verify:** `python -m pytest tests/test_agent_harness.py tests/test_options_model.py tests/test_key_rotator.py -q`

**Done:** every explicit or Auto request has bounded, non-resettable attempts, generation, tools, context, and time.

---

### Task 6: Integrate Gemini accounting and sanitized traces

**Files:**
- Modify: `backend/app/terminal/options_gemini.py`
- Modify: `backend/app/terminal/agent_harness.py`
- Modify: `backend/tests/test_agent_harness.py`
- Create: `backend/tests/test_agent_harness_traces.py`

**Interfaces:**
- Consumes: Task 5 reserve/account/deadline primitives.
- Produces: adapter-neutral attempt/token accounting and sanitized parent/child trace builders for later persistence.

**Action:** Integrate Gemini reasoning/output/total usage with the same counters. Add stage timers and stable routing, scope, context, model-budget, tool-budget, timeout, evidence, output, and provider failure codes. Traces may contain versions, IDs, counts, timing, usage availability, and failure metadata; they must never contain prompts, answers, provider bodies, credentials, capability tokens, or account rows.

- [ ] Test reported and missing usage, retry exhaustion, cancellation, terminal traces, and redaction of every forbidden field.
- [ ] Confirm RED, implement adapter integration and trace builders, then confirm PASS.

**Verify:** `python -m pytest tests/test_agent_harness.py tests/test_agent_harness_traces.py tests/test_options_gemini.py -q`

**Done:** both provider paths account consistently and traces are useful without leaking private/model content.

---

## Subplan H4 — Runtime and router

### Task 7: Migrate explicit specialist APIs and retire the catch-all

**Files:**
- Modify: `backend/app/terminal/options_agent.py`
- Modify: `backend/app/terminal/routers/options_agent.py`
- Modify: `backend/tests/test_portfolio_agent.py`
- Create: `backend/tests/test_specialist_api.py`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: explicit chain/report, portfolio-analysis, and portfolio-risk execution using registry factories.
- Produces: authenticated `POST /api/options-agent/portfolio/risk/chat` returning `answer`, `conversation_id`, `run_id`, `parent_run_id`, `agent_id`, `evidence_ids`, `risk_report_ids`, `risk_snapshot`, `created_at`, and `read_only`.

**Action:** Resolve `agent_id` through the registry; feed only detached projections to models. Integrate admission, shared budgets, sanitized traces, exact citation validation, session/generation rechecks, and atomic success persistence. Isolate history by owner, agent, scope, contract, and selected context, with at most four compatible turns. Legacy mixed conversations remain readable but continuation returns HTTP 409 with `conversation_scope_changed`. Remove external tools from specialist runs. Only after all callers and tests migrate, delete `@register_agent('options_monitor')` and the generic builder.

- [ ] Add API tests for success, schema/citation failure, cross-user IDs, stale session, cancellation, provider failure, history isolation, legacy continuation, and atomic persistence.
- [ ] Confirm RED, migrate explicit paths, then confirm PASS.
- [ ] Search for active catch-all calls before deletion; migrate each caller.

**Verify:** `python -m pytest tests/test_specialist_api.py tests/test_portfolio_agent.py tests/test_options_agent.py tests/test_options_report_chat.py -q`

**Done:** explicit endpoints execute distinct specialists; invalid/failed output never persists; no active backend runtime caller uses the catch-all.

---

### Task 8: Implement the tool-less master router and sticky follow-ups

**Files:**
- Modify: `backend/app/terminal/unified_chat.py`
- Modify: `backend/app/terminal/agent_registry.py`
- Modify: `backend/tests/test_unified_routing.py`
- Modify: `backend/tests/test_specialist_api.py`

**Interfaces:**
- Consumes: Task 7 specialist runtime and Task 1 `RouteAnswer`.
- Produces: registered fresh `master_router` using Agno `TeamMode.route`, with no tools and routes `chain | portfolio | risk | clarify`.

**Action:** Validate conversation ownership before routing or fetching. Router context contains trusted current scope plus only current/previous user questions treated as untrusted text. Preserve sticky scope for elliptical follow-ups. Return clarification for mixed/unsupported requests. Return 409 on topic change before new evidence acquisition. Saved reports bypass routing. Store router and specialist stages beneath one parent run.

- [ ] Test mocked real transport for each route, elliptical follow-up, mixed request, topic change, cross-user conversation, report bypass, router injection, and no-capability enforcement.
- [ ] Confirm RED, implement routing and parent/child traces, then confirm PASS.

**Verify:** `python -m pytest tests/test_unified_routing.py tests/test_specialist_api.py -q`

**Done:** Auto routing reaches exactly one specialist or clarification without granting the master data access.

---

## Subplan H5 — Evaluations and cross-interface handoff

### Task 9: Build and migrate offline evaluations

**Files:**
- Create: `backend/app/terminal/specialist_evals.py`
- Create: `backend/evals/specialist_cases.json`
- Create: `backend/evals/specialist_rubric.json`
- Create: `backend/tests/test_specialist_evals.py`
- Modify: `backend/app/terminal/options_evals.py`
- Modify: `backend/tests/test_options_evals.py`
- Modify: `backend/tests/test_portfolio_evals.py`
- Modify: `backend/tests/test_portfolio_risk_evals.py`

**Interfaces:**
- Consumes: production factories, projections, validators, API schemas, and failure codes from Tasks 1–8.
- Produces: versioned offline evaluator with no catch-all dependency.

**Action:** Define development and held-out cases with independently checked route, tool, citation, numeric expectations, and forbidden claims. Cover normal, partial, stale, missing, injection, forged citation, scope change, timeout, and provider failure. Report dataset/rubric/model/prompt/tool/calculation versions, sample counts, routing/numeric/citation/abstention results, calls, and p50/p95 latency. Keep live mode explicit opt-in and never label replay as model quality. Migrate `options_evals.py` and its three named test modules from `build_agent` to registered production specialist factories/projections; preserve explicit offline/live behavior.

- [ ] Write evaluator tests and confirm RED.
- [ ] Implement offline evaluation and confirm PASS.
- [ ] Migrate the existing options, portfolio, and portfolio-risk evaluation callers and confirm their existing CLI tests pass.

**Verify:** `python -m pytest tests/test_specialist_evals.py tests/test_options_evals.py tests/test_portfolio_evals.py tests/test_portfolio_risk_evals.py -q`; `python -m app.terminal.specialist_evals --mode offline`; and the existing `options_evals` chain/portfolio/portfolio-risk CLI commands.

**Done:** no evaluation caller depends on the catch-all, cases exercise required failure modes, and reports distinguish offline replay from live model quality.

---

### Task 10: Generate frozen fixtures and the Part 2 handoff

**Files:**
- Create: `backend/evals/fixtures/specialist_api/chain.json`
- Create: `backend/evals/fixtures/specialist_api/portfolio.json`
- Create: `backend/evals/fixtures/specialist_api/risk.json`
- Create: `backend/evals/fixtures/specialist_api/clarify.json`
- Create: `backend/evals/fixtures/specialist_api/scope_change.json`
- Create: `docs/superpowers/plans/SPECIALIST_AGENTS_HANDOFF.md`

**Interfaces:**
- Consumes: actual response models, endpoint behavior, error codes, and passing results from Tasks 7–9.
- Produces: sanitized frozen contract examples and a self-contained cross-interface handoff.

**Action:** Generate all fixtures from actual application models or tested API responses, not handwritten approximations. Use synthetic UUIDs and non-sensitive values. The handoff must include the Part 1 commit SHA, prerequisite branch/state, agent/scope map, endpoint paths, request and response fields, error/status behavior, fixture locations, commands run, results, and explicitly deferred work. Include a warning that Part 2 must not run on a pre-Part-1 codebase. Do not include prompts, answers from real users, account rows, provider payloads, capability tokens, or credentials.

- [ ] Generate the five fixtures and validate each against its production Pydantic/API model.
- [ ] Add a lightweight fixture-schema test to `backend/tests/test_specialist_evals.py` and confirm PASS.
- [ ] Write the handoff using verified repository state and command results.
- [ ] Search the fixtures/handoff for known sensitive field names and secret sentinels.

**Verify:** `python -m pytest tests/test_specialist_evals.py -q`; parse all five JSON files; and verify `SPECIALIST_AGENTS_HANDOFF.md` names the exact commit, endpoints, scopes, fixtures, and successful commands.

**Done:** another coding interface can start Part 2 from the completed commit and implement UI/docs without inventing backend contracts.

## Final verification

Run from `backend`:

```powershell
python -m pip check
python -m pytest tests/test_specialist_agents.py tests/test_specialist_mcp.py tests/test_portfolio_mcp.py tests/test_options_mcp.py -q
python -m pytest tests/test_agent_harness.py tests/test_agent_harness_traces.py tests/test_options_model.py tests/test_options_gemini.py tests/test_key_rotator.py -q
python -m pytest tests/test_specialist_api.py tests/test_portfolio_agent.py tests/test_options_agent.py tests/test_options_report_chat.py tests/test_unified_routing.py -q
python -m pytest tests/test_specialist_evals.py -q
python -m app.terminal.specialist_evals --mode offline
rg "register_agent\('options_monitor'\)|\bbuild_agent\(" app tests
```

The final search must show no active catch-all registration or caller. Run an independent whole-branch review and resolve all Critical/Important correctness or security findings with failing tests first.

## Success criteria

- Three isolated specialists and one tool-less router work through production APIs.
- Permissions are enforced at MCP discovery and invocation, not only in prompts.
- Request budgets, deadlines, retries, histories, and traces remain isolated and bounded.
- Existing deterministic finance behavior and historical reads remain compatible.
- The catch-all is removed after migration.
- The offline evaluator and sanitized Part 2 handoff are complete and passing.

