# Part B — fees, compliance, account risk and evaluations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Checkboxes track verified work, not optimistic completion.

**Goal:** Complete pure fee/risk calculations and independent acceptance suites.
**Architecture:** Develop deterministic numerical work in an isolated checkout. Receive normalized source bundles from A; never fetch broker data or edit A's capture path.
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
Owner: second checkout/chat, branch codex/agents-remaining-b. Phase coverage: P6 fees/payoffs, P7 reconciliation mathematics, P8 risk/compliance, P9 stress acceptance, P10 independent evaluations; contribute P11 CI tests.
Own indian_charges.py, quant_compliance.py, quant_risk.py, quant_attribution.py, quant_proposals.py, new analytics_remaining_risk.py and matching new tests; own new independent eval corpora/scripts only.
DO NOT edit analytics_capture.py, analytics_inputs.py, analytics_store.py, market/portfolio adapters, existing provider files, shared ledger STATE.md or COMPLETION-GAPS.md. Request contract changes through A's status file/handoff, do not silently diverge.
Status file: ../implementation/agents-v2/PART-B-STATUS.md.
Read shared contract and specific kernels, not all repo history. Wait only for A1 contract when needed; source-document research and numerical fixtures can start immediately. Context7 for library behavior; authoritative dated exchange/broker documents for financial rules.

### Task B1: Dated fees and net payoff reconciliation

**Files:** Modify indian_charges.py, quant_proposals.py; create tests/test_remaining_fees.py.
**Interfaces:** Consume normalized fee schedule, trades and StrategyProposal; preserve existing public payoff schema.

- [ ] Write failing tests: test_entry_exit_different_effective_dates; test_exercise_assignment_charges; test_fee_rounding_matches_dated_contract_note; test_unknown_broker_fee_blocks_net_total; test_invalid_lot_or_quote_rejected. Use sanitized independently reconciled expected integer-paise totals.
- [ ] Run `python -m pytest tests/test_remaining_fees.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Define source-revision/effective-date schedule applicability for brokerage, exchange charges, statutory fees, settlement/closing/exercise. Implement only documented rates and caps. Reconcile per component and total against authoritative examples/notes; do not assume free brokerage or zero closing charges.
- [ ] Run `python -m pytest tests/test_remaining_fees.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: reconcile dated complete cost schedules`. Update the part's status file with commit, result and next task.

### Task B2: Applicable stock bans, FutEq and margin calculations

**Files:** Modify quant_compliance.py; create tests/test_remaining_compliance.py.
**Interfaces:** Consume CapturedRiskBundle.rules/positions with verified applicability. Produce findings with input basis/source refs and explicit coverage.

- [ ] Write failing tests: test_index_not_subject_to_stock_ban; test_same_underlying_multiple_contracts_aggregate; test_sign_reversal_and_intraday_increase; test_expiry_elm_effective_dates; test_calendar_spread_rule_by_expiry; test_missing_span_components_unavailable.
- [ ] Run `python -m pytest tests/test_remaining_compliance.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Separate dated exchange rule applicability, account aggregate exposure limits and broker margin. Preserve declared scenarios versus verified operational inputs. Implement documented SPAN/ELM/calendar components only with complete inputs. Account/intraday coverage required for operational pass; no automatic order halt or execution side effects.
- [ ] Run `python -m pytest tests/test_remaining_compliance.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: evaluate verified aggregate compliance inputs`. Update the part's status file with commit, result and next task.

### Task B3: Combined account and proposed-strategy risk

**Files:** Create analytics_remaining_risk.py and tests/test_remaining_account_risk.py; modify quant_risk.py as needed.
**Interfaces:** Implement evaluate_remaining_risk exactly per shared contract; accepts server-bound StrategyProposal or None.

- [ ] Write failing tests: test_cross_evidence_proposal_rejected; test_existing_and_proposed_positions_net_once; test_overlapping_holdings_positions_partial; test_missing_funds_or_position_section_not_complete; test_combined_historical_repricing. Assert coverage remains partial for any required missing source.
- [ ] Run `python -m pytest tests/test_remaining_account_risk.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Normalize immutable captured positions and hypothetical proposal into one inventory with explicit netting basis. Aggregate delta/FutEq, stress and available margins; preserve separate gross/net/cost metrics. Require proven full coverage for complete-account verdicts. No broker/model/network imports.
- [ ] Run `python -m pytest tests/test_remaining_account_risk.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: evaluate combined captured account proposal risk`. Update the part's status file with commit, result and next task.

### Task B4: Cash-flow-aware performance reconciliation

**Files:** Modify quant_attribution.py; create tests/test_remaining_attribution.py.
**Interfaces:** Consume A's normalized adjusted prices, aligned daily beginning values, fills and external cash flows; preserve current HRP and sector metrics.

- [ ] Write failing tests: test_deposit_and_withdrawal_do_not_inflate_return; test_sector_contributions_reconcile_total; test_trade_inventory_reconciles_cash; test_short_history_does_not_disable_independent_metrics; test_missing_benchmark_only_disables_alpha.
- [ ] Run `python -m pytest tests/test_remaining_attribution.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Complete independently sourced performance reconciliation. Keep derivative metrics separate from cash sleeve HRP; no current-weight backfill. State return convention, cash-flow timing and source basis. Unknown inputs only disable dependent metrics.
- [ ] Run `python -m pytest tests/test_remaining_attribution.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `feat: reconcile portfolio cash flow performance`. Update the part's status file with commit, result and next task.

### Task B5: Independent tail and numerical acceptance corpus

**Files:** Create tests/test_remaining_tail_acceptance.py; modify quant_risk.py only for reproduced defects.
**Interfaces:** Existing stress and historical repricing functions; fixed independently computed reference fixtures.

- [ ] Write failing tests: test_tail_counts_249_250_999_1000_per_series_horizon; test_95_available_when_99_missing; test_stress_28_cells_independent_of_history; test_nonfinite_and_duplicate_scenarios_rejected. Assert exact insufficient_history_for_99pct reason for250–999 and reference losses/tail means.
- [ ] Run `python -m pytest tests/test_remaining_tail_acceptance.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Do not rewrite already implemented independent tails. Add representative dated scenario fixtures and verify horizon/pricing assumptions. Label synthetic fixtures synthetic; actual source coverage comes from A. Correct only demonstrated numerical or coverage defects.
- [ ] Run `python -m pytest tests/test_remaining_tail_acceptance.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `test: verify independent tail and stress acceptance`. Update the part's status file with commit, result and next task.

### Task B6: Independent model and integration evaluation pack

**Files:** Create backend/evals/analytics_router_remaining.v1.json and backend/evals/remaining_live_evals.py; tests/test_remaining_eval_guards.py.
**Interfaces:** Consume existing coordinator/selection/stage public contracts; tests use normalized contract fixtures independent of A's broker.

- [ ] Write failing tests: test_live_flag_required; test_no_private_account_data_in_eval_output; test_two_calls_include_prefetch; test_proposal_selection_no_third_call; test_continuation_rejects_changed_session. New corpus includes ambiguous multi-intent, statutory levies, missing source, mutation rejection and all role combinations.
- [ ] Run `python -m pytest tests/test_remaining_eval_guards.py -q`; confirm the named new behavior fails before implementation.
- [ ] Implement: Create a genuinely new heldout corpus before prompt changes; save initial outcomes separately from tuned regression scores. Actual model runs explicit-only using available local configured model, no downloads. Verify claim binding, malformed outputs, deadlines and provider differences; unavailable providers are recorded, not silently simulated.
- [ ] Run `python -m pytest tests/test_remaining_eval_guards.py -q`; all affected tests must pass. Record source prerequisites that cannot be verified.
- [ ] Commit only owned files: `test: add independent remaining analytics evaluations`. Update the part's status file with commit, result and next task.

## Final B acceptance and handoff
- [ ] Run all B tests, existing affected numerical/analytics tests and full backend suite in B checkout; pip check and offline eval modules.
- [ ] Run authorized explicit live model checks against synthetic/public fixtures; never copy A's private session. Broker fixtures remain A's responsibility.
- [ ] Fresh review of pure calculations and shared interface. Supply exact commit hashes, commands, outcomes, source citations/effective dates and external blockers in PART-B-STATUS.md.
- [ ] Hand A only owned-file commits. A integrates shared capture wiring and performs full signed-in end-to-end acceptance.
- [ ] Remote CI/Docker/release are final gates managed by A; B supplies reproducible tests/fixtures, not invented success.

## Copy-paste instruction for the other checkout/chat
Implement Part B only from this plan and 2026-11-13-remaining-shared-contract.md, baseline ca806c1. Read AGENTS.md. Preserve Part A's ownership; do not edit capture/adapters/provider files. Obtain A1's isolated contract commit before using the production model. Maintain PART-B-STATUS.md and return owned-file commit hashes plus tests and blockers. Work inline, loading only current task files. Do not push, deploy, trade, download models or copy credentials/databases.

