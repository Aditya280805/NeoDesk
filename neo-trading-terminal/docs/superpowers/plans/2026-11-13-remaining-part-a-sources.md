# Part A — authenticated sources and capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Checkboxes track verified work, not optimistic completion.

**Goal:** Finish source adapters and wire trusted evidence into the existing agents.
**Architecture:** Own acquisition, identity, normalization, private data, and capture. Consume B's pure evaluator through the shared bundle; keep calculations out of adapters.
**Tech Stack:** Python, FastAPI, Pydantic, SQLite, HTTPX, existing broker SDK; existing frontend where required.
**Spec:** ../implementation/agents-v2/PLAN.md; ../implementation/agents-v2/COMPLETION-GAPS.md; 2026-11-13-remaining-shared-contract.md.

## Global Constraints
All constraints and fixed v1 signatures in the shared contract apply. Start from ca806c1; preserve concurrent edits. Work inline to minimize repeated context. Read only current task files. Every changed behavior needs a meaningful failing regression, implementation, passing affected checks, commit and short resume record.

## Review Focus
- Stale or contradictory source dates must not produce current evidence.
- Cancellation must retain synchronous worker capacity and prevent stale publication.
- Partial holdings/positions/funds must not become complete account coverage.
- Cross-owner/session/proposal identity must fail before publication.
- Deadline exhaustion and source outages must preserve explicit missing data without adding MCP calls.

## Ownership and startup
Owner: this checkout/chat. Phase coverage: P1–P5 source gaps, P7 input gaps, P8 source gaps, P9 history coverage, P2/P11 authenticated integration.
Own existing analytics_capture.py, analytics_history.py, analytics_identity.py, analytics_sources.py, analytics_ban_source.py, analytics_inputs.py, analytics_store.py, portfolio_service.py, portfolio_normalization.py, portfolio_contracts.py, market.py, catalogue.py, analytics_handoff.py. Own new source modules below and matching tests. Touch provider-owned options_agent/server only through a separately reviewed isolated hunk if indispensable.
Status file: ../implementation/agents-v2/PART-A-STATUS.md.
Start by recording git status, current commit and sanitized source availability. Do not re-run completed model evaluations or rewrite existing numerical kernels.

### Task A1: Freeze integration model

**Files:** Create backend/app/terminal/analytics_remaining_contracts.py; tests/test_analytics_remaining_contracts.py (under backend).
**Interfaces:** Produce SourceStamp and CapturedRiskBundle exactly as shared contract.

- [ ] Write failing tests: test_bundle_rejects_naive_time; test_bundle_rejects_unknown_fields; test_bundle_requires_positive_owner; test_bundle_does_not_promote_partial_coverage. Assert ValueError on naive timestamp/owner0/extra raw envelope and preserve partial coverage.
- [ ] Run `python -m pytest tests/test_analytics_remaining_contracts.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Implement frozen validated models; validate normalized position/rule rows with existing schemas. Publish isolated contract commit to B before any dependent work.
- [ ] Run `python -m pytest tests/test_analytics_remaining_contracts.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: define remaining risk integration contract`. Update the part's status file with commit, result and next task.

### Task A2: Diagnose live portfolio and resolve verified identities

**Files:** Modify portfolio_service.py, portfolio_normalization.py, market.py, catalogue.py; tests/test_portfolio_service.py and test_portfolio_normalization.py.
**Interfaces:** Consume authenticated broker session and raw master fields privately; produce existing portfolio evidence schema.

- [ ] Write failing tests: test_empty_positions_are_distinct_from_transport_failure; test_exact_exchange_token_symbol_matches; test_ambiguous_isin_or_conflicting_token_stays_unresolved; test_session_change_discards_fetch. No invented empty response normalization.
- [ ] Run `python -m pytest tests/test_portfolio_service.py tests/test_portfolio_normalization.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Capture sanitized response SHAPES/error categories server-side from current owner; verify documented SDK responses before adding aliases. Fix only observed mismatches. Unique token/exchange/master identity required; identity_verified stays false unless required metadata is proven. Do not expose error bodies or account identifiers.
- [ ] Run `python -m pytest tests/test_portfolio_service.py tests/test_portfolio_normalization.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `fix: normalize verified authenticated portfolio sources`. Update the part's status file with commit, result and next task.

### Task A3: Adjusted history, benchmark, IV and pricing metadata

**Files:** Create analytics_market_sources.py and tests/test_analytics_market_sources.py; modify analytics_history.py, analytics_inputs.py and analytics_identity.py.
**Interfaces:** Produce existing surface_rows/pricing_by_expiry/iv_history/verified_returns inputs with SourceStamp; use documented normalized input types.

- [ ] Write failing tests: test_adjustment_basis_required; test_expiry_timestamp_not_inferred_from_date; test_ema200_multiwindow; test_series_horizon_scenario_counts_independent; test_source_token_contradiction_rejected. Assert unverified adjustment/rate/forward fields unavailable.
- [ ] Run `python -m pytest tests/test_analytics_market_sources.py tests/test_analytics_history.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Acquire authenticated available histories with bounded batches, dated actual expiry, matching futures/forward and verified rate convention. Preserve closed-bar semantics. Corporate-action adjustments require actual source factors. Missing historical option series stays unavailable; do not synthesize >=1000 scenarios. Reuse existing three-window EMA history implementation.
- [ ] Run `python -m pytest tests/test_analytics_market_sources.py tests/test_analytics_history.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: integrate provenance bound market histories`. Update the part's status file with commit, result and next task.

### Task A4: Previous OI, cash/futures basis and participant sessions

**Files:** Create analytics_positioning_sources.py and tests/test_analytics_positioning_sources.py; modify analytics_sources.py only as needed.
**Interfaces:** Produce previous-OI/price, synchronized cash_future_basis and parsed six-session participant history for existing kernels.

- [ ] Write failing tests: test_missing_previous_oi_is_not_zero; test_cash_future_timestamp_skew_unavailable; test_six_actual_sessions_skip_holidays; test_session_gap_blocks_change. Assert counts remain contracts, not delta/cash flow.
- [ ] Run `python -m pytest tests/test_analytics_positioning_sources.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Use verified prior publications/provider fields and actual dated trading sessions. Bind basis by underlying/expiry and documented synchronized timestamps. Keep imported versus official cache namespaces separate.
- [ ] Run `python -m pytest tests/test_analytics_positioning_sources.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: complete dated positioning source coverage`. Update the part's status file with commit, result and next task.

### Task A5: Authenticated fills, cash flows and daily portfolio inputs

**Files:** Create analytics_account_sources.py and tests/test_analytics_account_sources.py; modify analytics_inputs.py and portfolio_service.py.
**Interfaces:** Produce declared_attribution-compatible adjusted price dates/beginning values, matched trades and cash-flow rows; produce CapturedRiskBundle normalized positions/sources.

- [ ] Write failing tests: test_external_deposit_not_trading_profit; test_missing_fill_keeps_coverage_partial; test_derivatives_excluded_from_cash_hrp; test_daily_weights_not_backfilled; test_holdings_positions_overlap_not_double_counted.
- [ ] Run `python -m pytest tests/test_analytics_account_sources.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Map documented authenticated fills/trades and available cash ledger. Preserve source timestamps and bases; reconcile opening/closing inventory and corporate actions. A broker lacking ledger endpoints requires an explicitly validated import adapter, and live coverage remains partial until supplied.
- [ ] Run `python -m pytest tests/test_analytics_account_sources.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: capture reconciled account history inputs`. Update the part's status file with commit, result and next task.

### Task A6: Ban/rule/margin sources and capture integration

**Files:** Create analytics_rule_sources.py and tests/test_analytics_rule_sources.py; modify analytics_capture.py, analytics_handoff.py, analytics_ban_source.py.
**Interfaces:** Consume B evaluate_remaining_risk(bundle,proposal); produce existing role-scoped AnalyticsEvidence. A owns ALL shared wiring.

- [ ] Write failing tests: test_official_ban_matches_master_underlying_not_display_name; test_wrong_trade_date_unavailable; test_unknown_empty_day_format_unavailable; test_rule_effective_boundaries; test_capture_keeps_two_mcp_budget; test_session_or_policy_change_discards_report.
- [ ] Run `python -m pytest tests/test_analytics_rule_sources.py tests/test_analytics_capture.py tests/test_analytics_handoff.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Reuse mounted official ban fetch/cache. Map only verified stock-derivative underlying identities; index exclusion must be explicit. Acquire dated rule/fee/margin source records for B, provenance and coverage. Mount B output without passing raw account envelopes to model; scenario proposal binding remains server-side. Unknown SPAN/margin inputs stay unavailable.
- [ ] Run `python -m pytest tests/test_analytics_rule_sources.py tests/test_analytics_capture.py tests/test_analytics_handoff.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: wire verified sources into scoped risk evidence`. Update the part's status file with commit, result and next task.

## Final A acceptance
- [ ] Read-only authenticated smoke: portfolio sections, history/pricing dates, positioning and ban publication; report exact coverage and failures.
- [ ] Merge B's owned calculation commits, run shared interface and full backend tests, pip check and eval modules.
- [ ] Run frontend test/lint/build/browser if UI behavior changed. Verify progress, missing inputs, continuation/session expiry and mobile layout.
- [ ] Keep independent rollout flags off until source and release gates pass. Record Docker/remote CI results only when actually run.
- [ ] Consolidate COMPLETION-GAPS.md and STATE.md after both parts; remove stale chronological statements. Completion requires acceptance evidence for every P0–P11 row.

## Copy-paste instruction for this chat
Implement Part A only from this plan and the shared contract. Preserve existing provider changes and live session. Publish A1 contract commit to Part B, then continue A2–A5 independently. Integrate B at A6. Maintain PART-A-STATUS.md; do not reread the entire conversation.

