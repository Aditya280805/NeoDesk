# Portfolio Risk Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (the user's selected method) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add auditable, deterministic portfolio monitoring checks and user-owned limits to the existing portfolio chat.

**Architecture:** One Agno agent, modular Python services, private MCP. A pure evaluator consumes validated portfolio evidence and one immutable policy revision. Refreshes calculate reports without calling the model; chat explains exactly the report attached to its evidence.

**Tech Stack:** Existing pinned Python/FastAPI/Pydantic/Agno/MCP stack, SQLite, Next.js Pages Router and React. No dependency upgrades required by this plan.

**Spec:** `docs/superpowers/specs/2026-10-29-portfolio-risk-phase-2-design.md`, including the review refinements below. Status: reviewed planning proposal; implementation has not started. User requested improvements and this plan, not product-code changes in this turn.

## Global Constraints

- Preserve the Phase 1 architecture and two private read-only tools; no orders, strategy suggestions, external MCP clients or policy-editing tools.
- One backend worker; authenticated owner and session-generation checks everywhere evidence is read or published.
- Retain current one-active-user, six-chat-attempts/minute, four-global-request admission; refresh minimum five seconds and visible-page interval 60 seconds.
- Retain two agent calls, three model requests, 30-second model and 60-second overall deadlines, 65-second capability lifetime and three MCP reads including prefetch.
- Retain existing provider budgets, no model retries/fallback, 64 KiB model context and four historical messages maximum; include the risk report in that context budget.
- Keep broker/SQLite blocking work off the event loop. Cancelled workers retain execution capacity until they finish; final publication is fenced by cancellation, deadline and session generation.
- Exact decimal strings/null, no missing-to-zero coercion, no inferred margin/P&L semantics. Financial thresholds and observation-age policy start unset.
- Additive migrations and old chain/portfolio history compatibility; manual refresh bypasses broker cache, policy edits do not rewrite reports.
- Preserve the dirty checkout and existing user configuration. No blanket staging, resets, commits, pushes or deployment in this plan. Record task checkpoints in the existing `.superpowers/sdd` style ledger.
- Use `backend/.venv-harness/Scripts/python.exe`; do not replace the older environment. Live model/broker checks remain separately opt-in.

## Review Focus

1. Partial holdings can inflate concentration; incomplete denominators must produce neither pass nor a definitive ratio breach (Task 3).
2. Policy save and snapshot completion can race; each report keeps its captured revision and the UI identifies a superseded revision (Tasks 2, 4, 5).
3. Future/naive timestamps, midnight in India and stale cache entries must not appear fresh (Tasks 1, 3).
4. Booleans, oversized decimal exponents and recurring ratios must not bypass validation or alter threshold decisions (Tasks 1, 3).
5. Repeated instrument rows are not necessarily duplicate records; aggregation needs verified economic identity and coverage, without summing holdings and positions (Tasks 1, 3).

## Improvements from the review

- **Evidence metadata gap:** current `PortfolioRow` verifies a contract but does not carry a verified underlying grouping key; current funds/P&L provenance does not establish a total-margin denominator or P&L period. Add optional typed metadata with provenance. Leave it absent unless supported by an explicit adapter mapping and source evidence. No guessing from symbols or `provider_reported` labels.
- **Qualified breaches:** an expiry on a known open row can breach even when other rows are missing. A concentration ratio with an incomplete denominator cannot. Freshness and basis failures block current financial assessments; retain the observed figures as historical observations only.
- **Coverage and empty inputs:** show counts of passed, breached, unassessable and disabled checks. All-disabled is `cannot_assess`, never green. Empty complete positions can pass expiry when configured/fresh; empty holdings concentration and zero margin denominator cannot be assessed.
- **Numerical boundary safety:** compare ratios by cross-multiplication, not rounded division. Reject oversized policy values and handle extreme provider evidence as a bounded calculation failure rather than a server error.
- **Revision consistency:** optimistic policy updates, immutable per-run reports and a visible “evaluated with an older policy” label prevent silent mismatches.
- **Storage growth:** save each successful published report once, reference it from history, paginate reads and provide a dry-run-first maintenance command for old unreferenced reports. Never remove reports referenced by conversations or run records.
- **Operational visibility:** distinguish a check breach from an evaluation failure; log only identifiers, versions, reason codes and durations, never balances or broker payloads.

## Contracts and decisions

New modules live under `backend/app/terminal/`:

| Module | Responsibility |
|---|---|
| `portfolio_risk_contracts.py` | Policy, finding, report and response types |
| `portfolio_risk.py` | Pure deterministic evaluation, no I/O |
| `portfolio_risk_store.py` | Additive schema, owner-scoped revisions/reports, maintenance |

### Policy

`RiskPolicy` is a frozen, extra-forbidden value with `schema_version='portfolio-risk-policy.v1'`, `revision: int`, four strict boolean enable flags (default true), nullable `concentration_max_percent`, `expiry_window_days`, `margin_max_percent`, `loss_max_amount`, `loss_basis`, `loss_period`, and `max_observation_age_seconds`. Owner comes only from authentication/store, never request content.

Decimal settings are canonical decimal **strings** or null in JSON; reject numeric JSON values, booleans, blank strings, NaN/infinity, exponent notation and more than 24 total digits or 8 fractional digits. This prevents float decoding from changing a user threshold. Percentage ranges: concentration 0–100 inclusive; margin nonnegative (may exceed 100); loss nonnegative. Days: strict integer 0–365; age: strict integer 1–86400, or null. These bounds are input/service constraints, not recommended financial limits. Disabled checks retain settings but do not evaluate them.

The initial loss setting vocabulary is `loss_basis='broker_account_net_pnl'`, `loss_period='broker_trading_day'`, currency INR. Basis, period and amount must be all absent or all present. This names the supported evaluator contract; it does **not** assert Kotak supplies it. Unsupported provider semantics yield `unsupported_basis`; no row P&L summation substitutes for account P&L. Initial adapter support may be empty and must be shown as unavailable in settings.

Revision 0 is a read-only unset default for users without settings. A successful full-policy PUT creates revision 1 or increments by one. Update body is `RiskPolicyUpdate(expected_revision: int, policy: RiskPolicySettings)`; revision must be nonnegative strict integer. Unknown fields are rejected.

### Evidence extensions

Add optional `underlying_key` and `underlying_identity_basis` to `PortfolioRow`; do not equate contract verification with underlying verification. Group using a documented canonical identity (e.g. verified catalogue identity), never symbol text. Multiple legitimate holding lots may aggregate; ambiguous duplicates or overlapping inventory buckets block complete coverage unless the adapter proves they are disjoint.

Add optional typed `risk_inputs` to `PortfolioSnapshot`, default null for legacy snapshots. It contains optional account-level `used_margin`, `total_margin`, `account_net_pnl`, currency, basis/period identifiers, period start/end, source timestamp, and provenance paths. Define separate margin and P&L records so one cannot borrow the other's timestamp/basis. Do not accept browser/model-supplied records. Provider timestamp alone is not evidence of a documented financial basis. Keep `portfolio.v1` additive compatibility and test strict internal parsers explicitly.

### Reports and evaluation

`evaluate_portfolio_risk(snapshot: PortfolioSnapshot, policy: RiskPolicy, as_of: datetime) -> RiskReport` is pure. `as_of` must be timezone-aware UTC; broker timestamps must be timezone-aware, no future times, and section start <= finish <= as_of. Invalid time evidence produces `cannot_assess` for affected checks. Observation age equals `as_of - original section retrieval_started_at`; at maximum age is fresh, above is stale. Missing age policy yields `freshness_limit_not_configured`. Source-sensitive margin/loss also require their relevant trustworthy source timestamp to satisfy that age bound.

`RiskReport` has `schema_version='portfolio-risk.v1'`, UUID report/evidence IDs, policy revision, `calculation_version='portfolio-risk.1'`, evaluated_at, observation times, summary, coverage counts, limitations and four `RiskFinding` entries. Each finding has code, enabled flag, outcome (`pass|breach|cannot_assess`), decimal-string measured/limit or null, unit, numerator/denominator where relevant, affected row IDs, and machine reason codes. Disabled checks use `cannot_assess/check_disabled` and a distinct disabled coverage count.

- Concentration: use complete eligible INR holdings with verified grouping and nonnegative valuation. A nonzero quantity with unknown value/group or ambiguous overlap blocks assessment. Sum legitimate lots by key; largest group / positive total. Decide `largest * 100 > limit * total`. Do not use a partial subtotal as denominator. Negative values/short holdings are unsupported for this holdings-only ratio. Zero-quantity rows may be ignored only when their valuation is zero; contradictions block assessment.
- Expiry: verified open derivative quantities of either sign; known nonderivatives excluded, unknown instrument classification or quantity blocks a clean pass. With India calendar date D, expiry < D is `expired_open`; 0 <= expiry-D <= configured days is breach. No holiday/trading-session inference. Missing expiry blocks pass but does not erase a known row breach. Known zero positions excluded. Complete empty positions pass only with configured/fresh inputs.
- Margin: compatible documented INR margin record with nonnegative used and positive total, known source freshness. Decide `used * 100 > limit * total`. A zero denominator remains unassessable even when used is zero.
- Loss: documented account P&L of matching basis/currency/period, source freshness and current broker-day period. `loss=max(0,-net_pnl)`; breach only if loss > limit. No combining realized/unrealized/provider values of unknown overlap. No drawdown inference.

All maxima pass at equality. Limit unset blocks that check. Summary precedence: breach, cannot_assess, pass among enabled checks; disabled checks always remain visible. With zero enabled checks, summary cannot_assess. Use a bounded local Decimal context and magnitude guard; do not globally change arithmetic behavior. Report ratio display precision separately from exact numerator/denominator and never round before the threshold comparison.

### Transport and storage

Keep snapshot fields at their existing top level. Add `risk_report` to the portfolio MCP/public response via a separate typed `PortfolioRiskEnvelope` containing the existing snapshot fields plus report; avoid a recursive report inside the normalized snapshot. Update strict parsing/serialization deliberately. Model output adds exactly one `risk_report_ids` entry for new risk-enabled responses; historical replies without the field remain readable. Persist new prompt version `portfolio.2` while retaining old history contexts.

GET and PUT `/api/options-agent/portfolio/risk-policy` use existing authenticated user resolution. GET returns current policy and supported input capabilities. PUT returns saved revision, 409 on stale expected revision, 422 for validation and a sanitized retryable response for exhausted SQLite lock wait. User ID never comes from body/query. No MCP policy write tool. Do not modify `risk.py`, its existing settings or kill switch semantics.

Capture policy once at run admission before collection, then use it through report/tool/answer/persistence. A concurrent edit affects the next run only. Reports belong to authenticated users, and publication/history references are committed atomically within the existing cancellation/generation fence. Failed model runs may keep failure diagnostics but cannot create a successful answer. Snapshot refresh may publish a valid report without any model request.

## Task 1: Typed policy, risk input and report contracts

**Files:** create `backend/app/terminal/portfolio_risk_contracts.py`, `backend/tests/test_portfolio_risk_contracts.py`; modify `portfolio_contracts.py`, `portfolio_normalization.py` and their existing tests.

**Interfaces:** produce the types above; `RiskPolicySettings` excludes revision/owner, `RiskPolicy` adds revision. Optional `RiskInputs` records are defined in `portfolio_contracts.py` to avoid circular imports. Envelope types live in risk contracts.

- [ ] Write contract tests asserting string `"0"` survives, null remains null, JSON numeric/boolean/exponent inputs fail, 24-digit/8-place limits hold, extra fields fail, integer coercion fails, and legacy snapshots still round-trip identically when extensions are absent.
- [ ] Run `backend/.venv-harness/Scripts/python.exe -m pytest backend/tests/test_portfolio_risk_contracts.py -q` from the project with existing test import conventions; verify failures are missing-contract failures.
- [ ] Implement contracts and optional evidence mapping. For every new broker semantic mapping, record the source/provenance and fixture proving identity/basis/period; if unavailable, leave fields null. No speculative field aliases.
- [ ] Run the new tests plus existing portfolio contract/normalization tests from backend with `.venv-harness/Scripts/python.exe -m pytest tests/test_portfolio_risk_contracts.py tests/test_portfolio_contracts.py tests/test_portfolio_normalization.py -q`; all pass.
- [ ] Record actual changes and focused results in the Phase 2 ledger; obtain fresh spec/code review before Task 2.

## Task 2: Owner-scoped policy and report persistence

**Files:** create `backend/app/terminal/portfolio_risk_store.py`, `backend/tests/test_portfolio_risk_store.py`; integrate initialization in `server.py` using existing `Store` connection conventions.

**Interfaces:** `PortfolioRiskStore(store)`; `get_policy(user_id: int) -> RiskPolicy`; `update_policy(user_id: int, update: RiskPolicyUpdate) -> RiskPolicy`; `save_report(db, user_id: int, report: RiskReport) -> None`; `get_report(user_id: int, report_id: UUID) -> RiskReport | None`. `save_report` participates in the caller's transaction, never commits separately. All user IDs required, no default account.

- [ ] Write tests for default revision 0, first save 1, stale update conflict, two simultaneous updates yielding exactly one winner, cross-user report isolation, duplicate report id idempotency only for identical content, rollback, and migration over a database containing Phase 1 history.
- [ ] Run `.venv-harness/Scripts/python.exe -m pytest tests/test_portfolio_risk_store.py -q` from backend; confirm red before implementation.
- [ ] Create additive `portfolio_risk_policy_revisions`, `portfolio_risk_policy_heads` and `portfolio_risk_reports` tables with owner keys, unique owner/revision and immutable report payloads. Use transactional compare-and-swap for updates; bounded busy wait and sanitized conflict errors. Store canonical JSON without monetary float conversion.
- [ ] Run the same tests to green, including concurrent real SQLite connections. Add a maintenance module CLI with required age argument, default dry-run and explicit `--apply`; only delete old unreferenced reports, preserving references from both successful history and run records. Test dry-run changes nothing and referenced rows survive.
- [ ] Record checkpoint and fresh review. No automatic purge or policy revision deletion.

## Task 3: Pure risk evaluator and independent fixtures

**Files:** create `backend/app/terminal/portfolio_risk.py`, `backend/tests/test_portfolio_risk.py`, `backend/evals/portfolio_risk_cases.json`.

**Interfaces:** consumes Task 1 contracts; produces `evaluate_portfolio_risk` exactly as specified, with no broker/database/model access. UUID generation is report identity only; freeze it in comparison tests.

- [ ] Write independent fixtures: holdings 60+40 with maximum60 passes, maximum59.99 breaches; partial denominator cannot assess; legitimate same-key lots aggregate; ambiguous duplicates cannot pass; zero/negative denominators cannot assess. Assert raw cross-products for repeating decimal boundaries rather than duplicating evaluator formulas as expected outputs.
- [ ] Add expiry tests at D-1, D, D+window and D+window+1; 18:30 UTC India rollover, positive/negative/zero/unknown quantities, unknown classification, partial known breach, complete empty positions. Add margin/P&L matching and mismatched basis/currency/period, profit -> zero loss, missing -> null, exact limits and unsupported provider metadata.
- [ ] Add age equality/overage, future/naive timestamps, cache original time, disabled-all, missing limits and malformed/huge numeric input tests. A stale financial figure cannot yield current pass/breach.
- [ ] Run `.venv-harness/Scripts/python.exe -m pytest tests/test_portfolio_risk.py -q` from backend; confirm red.
- [ ] Implement evaluator with exact boundary comparisons, conservative coverage and explicit reason codes. Validate finite bounded results; convert arithmetic failures to affected-check `cannot_assess/calculation_unavailable`, not a generic successful report.
- [ ] Run focused tests to green and have a fresh reviewer independently inspect expected fixture arithmetic and coverage rules; record checkpoint.

## Task 4: Bind reports through MCP, API and agent harness

**Files:** modify `options_mcp.py`, `options_agent.py`, `agent_scope.py`, `routers/options_agent.py`, `server.py`; create `backend/tests/test_portfolio_risk_integration.py`; extend existing portfolio MCP/agent tests.

**Interfaces:** use Tasks 1–3 types/store/evaluator; policy routes and envelope follow contracts above. Keep the existing no-argument tool name and capability permissions.

- [ ] Write real MCP initialization/discovery/call tests asserting two reads return identical evidence/report/revision, a policy edit during collection affects only the next run, wrong report/evidence refs are rejected, old history loads, and refresh invokes zero model calls.
- [ ] Add API tests for unauthenticated access, cross-user attempts, 409 conflicts, invalid body, malformed report envelope, lock exhaustion, oversized context including report, logout and cancellation immediately before transaction commit. Assert no successful turn/report reference survives rollback.
- [ ] Run `.venv-harness/Scripts/python.exe -m pytest tests/test_portfolio_risk_integration.py -q` from backend; confirm red.
- [ ] Wire captured policies and deterministic reports into the immutable MCP envelope, API response, model context and atomic persistence. Require exactly current evidence and report IDs for new model outputs; rejection is a failed run, not an answer. Version the portfolio prompt and explain disabled/unavailable checks without treating a pass as account safety.
- [ ] Run new integration tests and all existing options/portfolio MCP and agent tests. Verify capacity retention, timeouts, scopes and history compatibility remain intact; fresh review/checkpoint.

## Task 5: Policy controls and visible risk monitoring

**Files:** create `frontend/src/components/PortfolioRiskPanel.tsx`, `PortfolioRiskSettings.tsx`, `frontend/src/lib/portfolioRisk.ts`, `frontend/tests/portfolioRisk.test.cjs`; modify `frontend/src/pages/options-chat.tsx`, evidence types as needed and `styles/options-chat.css`.

**Interfaces:** typed API policy/envelope/report contracts from Tasks 1/4; decimal values stay strings through inputs and rendering. Do not use JavaScript Number for monetary comparisons.

- [ ] Read applicable `frontend/AGENTS.md` and installed Next.js documentation before implementation. Write tests for unset versus zero, disabled-all, incomplete coverage, ratios/limits, unsupported margin/P&L capabilities and old history without reports.
- [ ] Add tests for PUT conflict preserving unsaved edits and requiring explicit reload/review; a policy save during refresh labels the old revision and makes the next eligible refresh use the new revision. Do not bypass refresh admission or rewrite prior reports. Late scope/logout responses cannot overwrite current state.
- [ ] Run `npm test` from frontend and confirm new assertions fail before implementation.
- [ ] Implement controls with units and no recommended limits, save/cancel/error state and accessible labels. Display evaluated revision, source/observation time, findings, affected rows and coverage. Keep prior evidence visibly stale on failure; stop monitoring on refresh errors and pause hidden-page requests. Live refresh calls only the snapshot endpoint, never chat.
- [ ] Run `npm test`, `npm run lint`, `npm run build`. Conduct controlled browser checks for save conflict, hidden pause, stale retained report and old-revision response. Record synthetic versus real visibility evidence explicitly; fresh review/checkpoint.

## Task 6: Evaluation, diagnostics and release record

**Files:** modify `backend/app/terminal/options_evals.py`, extend `backend/tests/test_options_evals.py`; create `backend/tests/test_portfolio_risk_evals.py`; update `docs/OPTIONS_AGENT.md`, `docs/OPTIONS_HARNESS_PROGRESS.md` and phase ledger.

**Interfaces:** extend existing CLI with `--scope portfolio-risk`, using the Task 3 dataset and real private MCP protocol. Preserve chain/portfolio invocations. Dataset/rubric/calculation/prompt/model versions are explicit result fields.

- [ ] Write tests for deterministic expected outcomes, correct evidence/report citation, missing-versus-zero, abstention, stale data, prompt attempts to edit policy/place orders, and a fixed held-out explanation rubric separate from implementation fixtures.
- [ ] Run `.venv-harness/Scripts/python.exe -m pytest tests/test_portfolio_risk_evals.py -q` from backend; confirm red, then extend replay and diagnostics. Offline outputs must retain `model_evaluated=false` and `cost=null`; model evaluations report actual metadata only when available.
- [ ] Add sanitized observability assertions: report/evidence IDs, revision, calculation version, enabled/assessed counts, durations, outcome and failure stage; no financial values/provider payloads/credentials in logs. Evaluation errors are operational failures, distinct from valid breach findings.
- [ ] From backend run `.venv-harness/Scripts/python.exe -m pip check`, `.venv-harness/Scripts/python.exe -m pytest tests -q`, and `.venv-harness/Scripts/python.exe -m app.terminal.options_evals` separately with `--scope chain`, `--scope portfolio`, `--scope portfolio-risk`. All required offline cases pass.
- [ ] From frontend run `npm test`, `npm run lint`, `npm run build`; capture independent whole-phase review and resolve material findings. Document unsupported live margin/P&L inputs honestly; fixture success is not broker support or model quality.
- [ ] Update setup/progress with actual counts, limitations, browser evidence and maintenance usage. Leave live Kotak/model checks explicitly unverified unless separately authorized and run. No deployment or completion claim until required gates pass.

## Planning review and handoff

Self-review completed: each design area maps to Tasks 1–6; each Review Focus item has an owning test. Interfaces, legacy compatibility and disabled/empty/partial semantics are specified above. No product code or tests were executed as implementation in this planning turn.

Context7 checked Pydantic Decimal and strict validation on 2026-10-29. Python and JSON strictness differ, so explicit boundary validators and both transport/unit tests are required; use pinned installed versions. Sources: https://github.com/pydantic/pydantic/blob/main/docs/api/standard_library_types.md and https://github.com/pydantic/pydantic/blob/main/docs/concepts/strict_mode.md.

Tree Ring CLI/store remains unavailable in this workspace; this document is the durable planning record, not a claim of memory synchronization. Preserve the user's selected subagent-driven execution after plan review. Implementation is pending review of this concrete plan.
