# Portfolio Evidence Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Let an authenticated user ask the existing agent about validated Kotak holdings, positions, orders and funds through a scoped private MCP tool.

**Architecture:** One Agno agent runner chooses a trusted chain or portfolio scope from the authenticated API route. Pure Python normalization and a session-aware snapshot service supply immutable evidence through the existing loopback MCP server. The portfolio API and UI share the validated data through a compatibility adapter.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, Agno 3.1.10, FastMCP 4.1.4, MCP 2.3.0, SQLite, Next.js Pages Router, React and TypeScript. Retain the constrained Phase 0 dependencies.

**Spec:** `docs/superpowers/specs/2026-10-28-modular-options-agent-design.md` — approved 2026-10-28.

## Global constraints

- One Agno agent, modular Python services, private MCP; one public backend worker.
- One active chat per user; six chat attempts per minute; four active options requests globally.
- Two agent tool calls; at most three model requests; 30-second model timeout; 60-second overall deadline.
- Preserve Phase 0 budgets: Gemini 4096 generation tokens including thinking; OpenAI 900 completion tokens; no automatic provider retry or fallback during a request.
- Snapshot refresh: one active request per user; at most one every five seconds; chat and refresh share admission limits across both scopes.
- Private capability lifetime remains 65 seconds; at most three MCP reads, including initial prefetch. Reject browser origins and non-loopback exposure.
- Missing data stays unavailable. Identity contradictions invalidate affected evidence. No model-generated numerical estimates.
- Broker SDK calls remain off the event loop. Cancellation retains capacity until synchronous work actually finishes.
- Preserve existing chain API/history and `/api/live` fields through adapters. Use additive storage changes only.
- Portfolio mode exposes no execution, policy-editing, strategy or external-client tools. Existing manual trading UI remains separately authorized.
- No live broker/model calls during offline tests. No secrets in fixtures, model inputs, logs, traces or source control.
- Use `backend/.venv-harness/Scripts/python.exe` for the validated local environment. Do not repair or replace the older `.venv` as part of this phase.
- The checkout contains substantial pre-existing changes. Preserve them. Do not use blanket staging or resets; execution checkpoints go in the ledger unless a task's changes can be isolated for a commit.

## Review focus

1. Logout/reconnect during an in-flight read must prevent publishing evidence from the old broker session — Tasks 3–5.
2. An empty broker response, an unavailable section and a genuine zero must remain distinguishable through the UI and model — Tasks 1, 2, 6, 7.
3. Unknown order sides and ambiguous instruments must not become valid SELL orders or matched contracts — Tasks 2, 3, 6.
4. A slow final section or delayed lock acquisition must not exceed the caller's deadline by starting more work after cancellation — Tasks 3, 4.
5. A large portfolio or very long provider string must fail with a bounded, explicit limitation rather than unbounded prompt growth or silent account truncation — Tasks 1, 3, 5.

## File map and dependency order

| Task | New files | Existing files touched | Responsibility |
|---|---|---|---|
| 1 | `backend/app/terminal/portfolio_contracts.py`, `backend/tests/test_portfolio_contracts.py` | — | Typed evidence and decimal contract |
| 2 | `backend/app/terminal/portfolio_normalization.py`, `backend/tests/test_portfolio_normalization.py` | — | Pure provider mapping, identity and calculations |
| 3 | `backend/app/terminal/portfolio_service.py`, `backend/tests/test_portfolio_service.py` | `market.py`, `portfolio.py`, `live.py`, relevant existing tests | Fetching, session generation, cache and compatibility |
| 4 | `backend/tests/test_portfolio_mcp.py` | `options_mcp.py`, `server.py`, `AGENTS.md` | Scoped discovery, authorization and immutable evidence |
| 5 | `backend/app/terminal/agent_scope.py`, `backend/tests/test_portfolio_agent.py` | `options_agent.py`, `routers/options_agent.py`, existing options tests | One runner, portfolio API and versioned evidence history |
| 6 | `frontend/src/components/PortfolioEvidence.tsx`, `frontend/src/lib/portfolioEvidence.ts`, `frontend/tests/portfolioEvidence.test.cjs` | `pages/options-chat.tsx`, `components/BrokerPortfolio.tsx`, `styles/options-chat.css` | Scope control, evidence display and compatibility UI |
| 7 | `backend/evals/portfolio_cases.json`, `backend/tests/test_portfolio_evals.py` | `options_evals.py`, evaluation tests, docs and CI if required | Evaluation, diagnostics, release proof |

Paths in the table below `backend/app/terminal/` or `frontend/src/` are relative to those directories where abbreviated. Execute Tasks 1–7 in order. Implementers may add small private helpers within the listed modules, but the public interfaces below are shared contracts.

## Contract decisions for this phase

These are implementation choices within the approved design, not claims about the provider's semantics.

- `PortfolioSnapshot` schema version is `portfolio.v1`; ID is `evidence_id: UUID`.
- `SectionName` is `holdings | positions | orders | funds`; state is `available | partial | unavailable | invalid`.
- Section arrays include a local `row_id` based on section and source index. Malformed rows produce issue records containing only row ID, field and safe code; raw provider payloads are never returned.
- State precedence: failed fetch -> unavailable; malformed envelope or exceeded payload bound -> invalid; valid envelope with row/field validation issues -> partial; valid empty or complete response -> available. Missing optional values remain null with limitations even in an available section. Partial sections expose valid rows and every issue; invalid/unavailable sections never contribute totals.
- `DecimalValue` fields use Python `Decimal | None`, finite only. JSON uses decimal strings or null. Currency is `INR` only when the feed contract establishes that basis; otherwise unknown. Quantities use canonical decimal strings to avoid silent rounding of broker data.
- Derived currency totals use decimal arithmetic and `ROUND_HALF_UP` to two places at the final output; unit prices retain source precision. Inputs, `formula_version` and calculation basis accompany derived values.
- Snapshot metadata includes `retrieval_started_at`, `retrieval_finished_at`, `source_observed_at`, `cache_age_seconds`, `atomic=false`, `exchange_freshness='unknown'` unless a verified exchange timestamp exists, and safe limitations. Each section has its own retrieval timestamps and optional provider timestamp.
- `source_observed_at` identifies the original broker observation. Every HTTP refresh gets a new evidence ID; cached data retains observation times and reports its age. Repeated tool reads within one chat return identical serialized evidence.
- For non-atomic collection, `source_observed_at` is the earliest section retrieval start and the per-section timestamps are authoritative. Do not claim that the account was observed at one instant.
- Retain the existing 15-second portfolio cache TTL. Authenticated manual refresh bypasses it. Partial snapshots may be cached for that TTL with their partial state intact; total failures and expired sessions are not cached.
- Bound each broker section to 1,000 rows and 1 MiB of serialized JSON before normalization. A section exceeding either limit becomes `invalid` with code `payload_limit`; do not silently omit excess rows. Bound returned human-readable strings to 160 characters and label shortened fields.
- Bound the serialized model input to 64 KiB, including history and evidence. Remove oldest history turns first (maximum four successful prior turns as today). If the current snapshot alone exceeds this budget, return a safe 503 reason `context_limit`, retain the snapshot endpoint for manual inspection, and do not invoke the model. No silent evidence truncation.
- Portfolio request body is `{message, conversation_id?}`; reject extra fields so user IDs and market selections cannot be smuggled into this scope. It uses the existing 2,000-character nonblank message rule.

---

### Task 1: Define typed portfolio evidence and numeric rules

**Files:** Create `backend/app/terminal/portfolio_contracts.py` and `backend/tests/test_portfolio_contracts.py`.

**Interfaces:**
- Produce Pydantic models `PortfolioSnapshot`, `PortfolioSection`, `PortfolioRow`, `PortfolioIssue`, `ValueProvenance`, and `SectionObservation`.
- `PortfolioSnapshot` contains the metadata above, `sections: dict[SectionName, PortfolioSection]`, `summary: dict[str, Decimal | None]`, and `limitations: list[str]`.
- `PortfolioSection` contains `state`, `rows`, `values` (funds), `issues`, retrieval timestamps, `provider_timestamp`, and `source_count`.
- `PortfolioRow` contains `row_id`, normalized identity, typed quantity/price/value/P&L fields, explicit side/status when applicable, `provenance` and `issues`. Keep fields relevant to each row type nullable; never fill unknowns with invented defaults.
- `SectionObservation` contains `raw: object | None`, retrieval timestamps and `error_code: str | None`; this transport-only object is never sent to the model or persisted as raw evidence.
- `parse_decimal(value: object, *, allow_negative: bool = False) -> Decimal | None`: empty/missing returns None; malformed/nonfinite/boolean or disallowed negative raises ValueError.
- `serialize_snapshot(snapshot: PortfolioSnapshot) -> str`: deterministic JSON field values, no NaN/Infinity, decimal strings, UUID/timestamp serialization.

- [x] Write `test_decimal_missing_zero_invalid_and_signed_values` with assertions: None/empty -> None, `"0"` -> Decimal('0'), `"0.10"` remains exact, booleans/NaN/Infinity raise, `"-2"` accepted only with allow_negative.
- [x] Write `test_snapshot_json_roundtrip_preserves_zero_and_missing` asserting JSON zero is `"0"`, missing is null, and revalidation preserves the original values and schema version.

  Core assertions: `assert parse_decimal(None) is None`, `assert parse_decimal('0') == Decimal('0')`, and `assert parse_decimal('-2', allow_negative=True) == Decimal('-2')`.
- [x] Run `python -m pytest tests/test_portfolio_contracts.py -q -p no:cacheprovider` from backend using the validated interpreter; confirm missing-interface failures before implementation.
- [x] Implement the models and helpers, including explicit issue codes and optional identity verification fields. Do not attach transport exceptions or raw payloads to public models.
- [x] Rerun that command and require all tests to pass. Record the task checkpoint in `docs/OPTIONS_HARNESS_PROGRESS.md`.

### Task 2: Normalize provider data and calculate only supported values

**Files:** Create `backend/app/terminal/portfolio_normalization.py` and `backend/tests/test_portfolio_normalization.py`.

**Interfaces:**
- Consume Task 1 models and `parse_decimal`.
- `normalize_portfolio(observations: dict[SectionName, SectionObservation], catalogue: list[dict], *, observed_at: datetime) -> PortfolioSnapshot`.
- `resolve_portfolio_instrument(raw: dict, catalogue: list[dict], *, holding: bool) -> dict`: normalized identity and verification status; no DB/network access.
- `to_legacy_portfolio(snapshot: PortfolioSnapshot) -> dict`: existing field names with finite number/null values and additive `quality`, `evidence_id` and safe `section_errors` fields. Calculations happen before conversion to legacy floats.

- [x] Write tests `test_empty_failed_and_invalid_sections_are_distinct`, `test_missing_quantity_keeps_issue_and_blocks_aggregate`, `test_unknown_side_stays_unknown`, `test_missing_multiplier_blocks_derived_position_pnl`, and `test_bad_denominator_never_defaults_to_one`. Assert explicit section states and null affected totals; retain valid zero rows in evidence even if the legacy UI filters closed positions.
- [x] Write `test_provider_pnl_and_calculated_pnl_keep_distinct_bases`: provider MTM is retained with its label; missing MTM is derived only from complete validated cash-flow, quantity, price and scale inputs. No sum mixes holdings with potentially overlapping position values.
- [x] Write `test_holdings_decimal_rounding_and_provenance`: three units at 0.10 cost and 0.20 price produce invested 0.30, value 0.60 and P&L 0.30; record the input paths/formula. Add a final-half-cent case proving ROUND_HALF_UP rather than binary-float rounding.
- [x] Write `test_identity_conflict_or_ambiguity_disables_match`: contradictory exchange/token/symbol yields an invalid row, duplicate catalogue symbol matches remain unresolved, and expiry/strike/type disagreements never produce a matched contract. Catalogue placeholder/defaulted metadata is not labelled provider-verified.
- [x] Run `python -m pytest tests/test_portfolio_normalization.py -q -p no:cacheprovider`; confirm failure before implementation.
- [x] Implement known provider aliases from `portfolio.py` and existing Kotak fixtures. For missing buy/sell components, do not assume zero. Prefer authoritative supplied net quantity when valid; a calculated alternative requires all components. Preserve provider totals separately from derived totals. Unknown units/currency/scaling block the affected arithmetic.
- [x] Implement the legacy adapter: preserve fields including `holdings_value`, `invested`, `holdings_pnl`, `available`, `reserved`, `equity=None`, rows and `synced_at`. Never map unknown order side to SELL. Partial quality must not hide every valid row; unavailable/invalid whole sections receive safe section errors.
- [x] Rerun contract and normalization tests; checkpoint the tested mapping rules and formula version in the ledger.

### Task 3: Build session-aware collection and reuse it in the website

**Files:** Create `backend/app/terminal/portfolio_service.py`, `backend/tests/test_portfolio_service.py`; modify `market.py`, `portfolio.py`, `live.py`, `tests/test_kotak_signin.py`, `tests/test_user_isolation.py`, and existing live tests only where the new truthful contract changes expectations.

**Interfaces:**
- Add `UserMarketSession.generation: str` (random UUID on creation/re-authentication/invalidation) and `Market.session_generation(user_id: int) -> str`; no default user ID in new service methods.
- `PortfolioSnapshotService(market, store)` exposes `fetch(user_id: int, *, expected_generation: str, force: bool = False, deadline_monotonic: float | None = None) -> PortfolioSnapshot` (synchronous) and `assert_generation(user_id: int, expected_generation: str) -> None`.
- Keep `portfolio.snapshot(market, store, user_id, force=False) -> dict` as the legacy entry point; it uses the shared service and Task 2 adapter.
- Use the per-session cache for normalized observations and original timestamps. Preserve thread safety under existing market locks; publish cache only if generation still matches.
- Service wrappers hold no independent cache: both the legacy helper and app-owned service instance use the same `UserMarketSession` cache, preventing duplicate or inconsistent observations.

- [x] Write `test_collection_partial_failure_and_auth_expiry`: one unavailable section yields labelled partial evidence; all sections unusable yields a controlled failure; authentication expiry fails the entire request. Do not persist raw exception messages.
- [x] Write `test_user_generation_cache_and_forced_refresh`: same user/session reuses observation within 15 seconds, different users cannot share it, forced refresh bypasses it, each delivery has a new evidence ID with original observation time retained on cache hits.
- [x] Write `test_inflight_disconnect_or_reconnect_cannot_publish_old_cache` using threading events, not timing sleeps. Test all relevant session replacement paths (`sign_in`, `connect`, `disconnect`, successful `broker_login`, authentication invalidation). Existing auth logout already calls disconnect; verify that path.
- [x] Write `test_deadline_checked_before_each_broker_call`: a blocked lock or slow first call consumes the remaining deadline; later sections are not fetched after deadline. A valid partial snapshot may be returned when individual section calls fail within the deadline; overall deadline expiry does not become a successful partial result.
- [x] Write `test_payload_limits_and_long_strings`: 1,001 rows or a payload over 1 MiB marks that section invalid with a safe code; long descriptive strings are bounded and flagged, never executed as instructions.
- [x] Run service tests and confirm failures. Implement sequential bounded broker fetches (`holdings`, `positions`, `limits`, `order_report`), capture per-section timings, use Task 2 normalization and check generation before publishing results. Read the instrument catalogue under a DB context without holding that DB connection during broker network calls.
- [x] Update the legacy path to share this service/cache. Retain existing login cache warming and `/api/live?refresh=true`. Verify cancellation's order lookup cannot treat UNKNOWN side/status as authorization to mutate an order; do not add any new execution capability.
- [x] Run `python -m pytest tests/test_portfolio_service.py tests/test_kotak_signin.py tests/test_user_isolation.py tests/test_live_execution.py -q -p no:cacheprovider`. Update fixtures only where they previously depended on fabricated defaults, documenting why. Record checkpoint.

### Task 4: Add the portfolio MCP tool with server-enforced scope

**Files:** Modify `options_mcp.py`, `server.py`, `AGENTS.md`; create `backend/tests/test_portfolio_mcp.py`; preserve `tests/test_options_mcp.py`.

**Interfaces:**
- `OptionsMCP(snapshots, port=8766, *, portfolio_service=None)` preserves current construction and gains the Task 3 service.
- `connection(user_id, context, run_id, *, scope='chain', session_generation=None)` is the existing async context manager with additive keyword arguments. Portfolio requires context=None and a captured generation; chain retains the existing OptionsContext contract.
- Capability gains `scope`, `allowed_tools: frozenset[str]`, captured generation for portfolio and a monotonic request deadline. Derive allowlist from scope in trusted code; never accept it from the model.
- `MCPConnection.portfolio_snapshot() -> dict` calls `get_portfolio_snapshot` with `{}`. Existing `.snapshot()` keeps the chain path.
- Add FastMCP middleware with `on_list_tools` and `on_call_tool`; read capability from `get_http_request().scope`. Filter discovery and check invocation against the allowlist before reading any data.

- [x] Verify middleware signatures against installed FastMCP 4.1.4 source. Context7 references below describe the API but do not authorize a dependency upgrade.
- [x] Write real protocol tests asserting chain discovery lists only `get_option_snapshot`, portfolio discovery only `get_portfolio_snapshot`, and direct invocation of the other tool fails even when its name is known.
- [x] Add tests for missing/expired/revoked capabilities, browser Origin rejection, unexpected model arguments, user isolation and generation mismatch. Prove the broker is not called on rejected requests.
- [x] Add `test_portfolio_tool_reuses_immutable_snapshot_and_budget`: prefetch plus two tool reads return byte-equivalent evidence, call the collector once and reject a fourth read. Evidence mutation by a caller cannot change later reads.

  Core assertions after three reads: `assert first == second == third`, `assert collector.call_count == 1`, and `assert discovery_names == ['get_portfolio_snapshot']` for portfolio scope. Perform the forbidden call through the protocol session, not only Agno's filtered tool list.
- [x] Add `test_cancelled_portfolio_read_retains_pending_capacity` with a blocking worker. Cancellation frees neither user nor global admission until the worker ends; a queued section fetch is not started once its deadline is over.
- [x] Run `python -m pytest tests/test_portfolio_mcp.py -q -p no:cacheprovider` and confirm failures. Implement the tool, middleware, scoped serialization and common pending-worker accounting. Keep exception text sanitized before FastMCP logging.
- [x] Wire the shared service from app construction and update AGENTS.md's one-tool rule to the approved two scoped read-only tools. Run both MCP test files and record checkpoint.

### Task 5: Add portfolio chat to the existing agent and history

**Files:** Create `backend/app/terminal/agent_scope.py`, `backend/tests/test_portfolio_agent.py`; modify `options_agent.py` and `routers/options_agent.py`; extend existing Gemini/harness fixtures where reusable.

**Interfaces:**
- `PortfolioChatRequest(message: str, conversation_id: UUID | None)` and `PortfolioAnswer(answer: str, evidence_ids: list[UUID])` in `agent_scope.py`; one required evidence ID, exact current ID checked after model execution.
- `AgentScope` defines scope, prompt version, allowed tool, stored context and output contract. `make_scope(scope: Literal['chain','portfolio'], context: OptionsContext | None) -> AgentScope` selects only trusted application definitions.
- Keep `OptionsAgent.chat(user_id, ChatRequest)` and `snapshot(user_id, OptionsContext)`. Add `portfolio_chat(user_id, PortfolioChatRequest)` and `portfolio_snapshot(user_id)` wrappers around common private execution/admission methods in the same OptionsAgent instance.
- New authenticated routes: POST `/api/options-agent/portfolio/snapshot` (no caller context), POST `/api/options-agent/portfolio/chat`.
- Portfolio chat response: `{conversation_id, run_id, answer, evidence_ids, portfolio_snapshot, created_at, read_only:true}`. No portfolio IDs are inserted into the chain `snapshot_ids` field.
- Portfolio conversation context is `{schema_version:'portfolio.v1',scope:'portfolio'}`. Existing chain context and responses retain their current shapes. History branches on stored context; portfolio turns expose `portfolio_snapshot`, chain turns retain `snapshot`. Existing owner checks apply to both.

- [x] Write authenticated API tests for portfolio snapshot and chat with the real MCP transport and controlled broker/model fixtures. Disable the chain fixture deliberately: portfolio chat must still work and must never fetch a chain.

  Core success assertions: `assert reply.status_code == 200`, `assert body['evidence_ids'] == [body['portfolio_snapshot']['evidence_id']]`, `assert body['read_only'] is True`, and `assert chain_fetch.call_count == 0`.
- [x] Test 401 unauthenticated, 404 cross-user history, 409 cross-scope conversation reuse, 422 extra body fields, and equal rate/concurrency enforcement across chain and portfolio routes. Both wrappers use the existing limiter state.
- [x] Test schema validation rejects wrong/missing/foreign evidence IDs, empty output and incomplete runs; failed answers are not persisted. Test generation is rechecked after model completion and before saving/returning an answer, so reconnection while the model runs invalidates the reply.
- [x] Test all-missing funds and an empty holdings list produce different prompts with explicit section states; instructions disallow invented zero values, trades, strategy advice and unsupported freshness claims. Provider strings and prior messages stay outside privileged instructions.
- [x] Test the 64-KiB input limit: remove oldest history first; oversize current evidence prevents any model invocation and records `context_limit`. Store safe trace metadata for scope, evidence ID, schema, data quality, provider/model/prompt/tool versions, timings and available token usage.
- [x] Run `python -m pytest tests/test_portfolio_agent.py -q -p no:cacheprovider` and confirm failures. Implement the shared runner and scope definitions, preserving Phase 0 cancellation, cleanup and error handling.
- [x] Exercise actual Agno+SDK serialization with controlled HTTP for Gemini portfolio tool call -> structured answer, and OpenAI portfolio structured answer. Assert only authorized tool declarations and exact evidence references.
- [x] Run all `test_options_*.py` and new portfolio backend tests. Confirm an old chain history fixture remains readable and unchanged. Record checkpoint.

### Task 6: Add portfolio scope and truthful evidence display

**Files:** Create `frontend/src/components/PortfolioEvidence.tsx`, `frontend/src/lib/portfolioEvidence.ts`, `frontend/tests/portfolioEvidence.test.cjs`; modify `frontend/src/pages/options-chat.tsx`, `frontend/src/components/BrokerPortfolio.tsx`, `frontend/src/styles/options-chat.css`.

**Interfaces:**
- Export `PortfolioSnapshot` TypeScript contract mirroring Task 1's JSON wire format and `formatDecimal(value: string | null, places?: number): string` from `portfolioEvidence.ts`. Use exact string/decimal formatting; never coerce null to zero or do portfolio arithmetic in JavaScript.
- `PortfolioEvidence({snapshot}: {snapshot: PortfolioSnapshot})` displays available sections, source times/cache age, invalid/missing-data issues and labelled summaries.
- Chat scope is `chain | portfolio`, selected in the page. Portfolio mode hides irrelevant market controls and uses Task 5 routes. Scope changes clear conversation/evidence, increment the existing request revision and stop monitoring.

- [x] Read `frontend/AGENTS.md` and the bundled Next.js Pages Router client-data guide before editing.
- [x] Add Node tests for `formatDecimal`: null -> `Unavailable`, `"0"` displays zero, `"0.10"` retains correct precision, negative P&L stays negative, and large decimal strings do not lose digits through floating-point conversion. Confirm failures before implementing the formatter.
- [x] Implement PortfolioEvidence with explicit empty/partial/unavailable/invalid states. Show cached observation time rather than implying a cache hit was a fresh exchange quote. Label provider versus calculated values and unknown freshness.
- [x] Extend the chat page's discriminated reply/turn types. Reuse visible-page 60-second refresh behavior, failure stop and existing revision guards; scope changes invalidate both late snapshots and late answers. Preserve earlier turn evidence when the displayed snapshot refreshes.
- [x] Update BrokerPortfolio's quantity/side types and rendering for null/UNKNOWN and additive quality issues. Use nullish price fallback rather than truthiness so a genuine zero is not discarded. Preserve existing manual order confirmation behavior and catalogue-only trade links.
- [x] Run `npm test`, `npm run lint`, `npm run build` from frontend and require successful exits.
- [x] In an isolated browser fixture session, verify both scope controls, valid zero display, missing sections, partial rows, failed-refresh retention, hidden-page pause, and delayed reply after scope change. Use controlled backend/model responses and a test account, never production broker credentials. Record the scenario results and checkpoint.

### Task 7: Evaluation fixtures, documentation and release evidence

**Files:** Create `backend/evals/portfolio_cases.json`, `backend/tests/test_portfolio_evals.py`; extend `backend/app/terminal/options_evals.py`, `backend/tests/test_options_evals.py`, `docs/OPTIONS_AGENT.md`, `docs/OPTIONS_HARNESS_PROGRESS.md`, and the repository-root CI workflow only if its current commands omit the new tests.

**Interfaces:**
- Extend the evaluation CLI with `--scope chain|portfolio` (default chain), preserving `--mode offline|live-model|live-broker`.
- Portfolio fixtures contain synthetic raw observations, expected quality/derived values and answer-review criteria. Dataset version is `portfolio-evals.v1`; no real holdings/account identifiers are committed.
- Reports include scope, dataset/rubric versions, mode, `model_evaluated`, provider/model when called, per-case checks, latency and available usage. Cost is null/unknown unless an explicit valid price table is supplied; never report unknown cost as zero.

- [ ] Add fixtures for: empty account, genuine zero, missing quantity/amount, partial endpoint failure, unknown side, conflicting identity, ambiguous catalogue match, unknown exchange timestamp, injected provider text, cross-scope/user request, and unsupported execution/strategy request. Independently hand-check decimal expected values and keep held-out cases separate from prompt examples.
- [ ] Write `test_portfolio_offline_evaluation_uses_real_mcp_and_reports_no_model` asserting all contract/calculation checks and `model_evaluated=false`. Write CLI compatibility tests proving the original chain mode and fixtures still run unchanged.
- [ ] Run evaluation tests and confirm failures. Implement mode-specific execution; live modes remain explicit. Model evaluation checks structured references and numeric concepts plus an exported human-review rubric for completeness, interpretation and abstention. Do not claim regex checks prove prose accuracy.
- [ ] Document routes, scope/tool matrix, decimal wire format, cache/session behavior, per-section limitations, input/payload bounds, troubleshooting and live-check commands. List strategy/scanner/risk/background work as later phases.
- [ ] Run backend `python -m pip check`, `python -m pytest tests -q -p no:cacheprovider`, `python -m app.terminal.options_evals`, and `python -m app.terminal.options_evals --scope portfolio`; run frontend `npm test`, `npm run lint`, `npm run build`. Record exact observed outcomes.
- [ ] Obtain a fresh read-only review of the Phase 1 changes and resolve material findings with regression tests. Inspect task-targeted whitespace/diff checks; do not revert unrelated existing changes.
- [ ] Update the ledger with implemented acceptance criteria, review results and separately unverified live provider/broker gates. A local model key alone does not prove free-tier eligibility or authorize claiming live success. Final handoff links the setup guide and reports remaining live checks truthfully.

## Self-review and coverage

- Spec's data contract, missing/zero, identity, precision and provenance: Tasks 1–2.
- Reuse of existing portfolio behavior, session cache and broker lifecycle: Task 3.
- Private scoped MCP, immutable evidence, tool limits and cancellation: Task 4.
- Authenticated chat, common harness, history, traceability and bounded model context: Task 5.
- Visible-page monitoring, late response handling and compatibility UI: Task 6.
- Independent calculations, model-quality evaluation and separate live gates: Task 7.
- All five Review Focus conditions have explicit tests in their owning tasks.
- Future strategy, portfolio risk policy, scanner, background scheduler, historical data and fine-tuning are intentionally outside this Phase 1 plan.

## References and handoff

Context7 consulted 2026-10-28: FastMCP `on_list_tools` returns tool objects that can
be filtered; `on_call_tool` exposes `context.message.name`; `get_http_request()`
provides the HTTP request. Verify against pinned source during Task 4:
https://github.com/prefecthq/fastmcp/blob/main/docs/servers/middleware.mdx
https://github.com/prefecthq/fastmcp/blob/main/docs/python-sdk/fastmcp-server-dependencies.mdx

Tree Ring Memory guidance has been read, but no local CLI/store was available at
the last check. The approved spec, this plan and the ledger are repository records;
no Tree Ring capture is claimed.

Execution recommendation: native implementation in the current session with one
fresh final reviewer. These tasks share contract and lifecycle interfaces and are
best executed sequentially. Per-task subagent implementation/review remains an
available alternative if the user prefers more independent review checkpoints.
