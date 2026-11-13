# Part B Status — Fees, Compliance, Risk, and Evaluations

- Baseline: ca806c1
- Branch: codex/agents-remaining-b
- Status: Complete and Verified
- Completed Tasks:
  - Task B1: `feat: reconcile dated complete cost schedules` (commit `6adcd95`)
    - Files: `indian_charges.py`, `quant_proposals.py`, `tests/test_remaining_fees.py`
    - Tests: `tests/test_remaining_fees.py` + `tests/test_analytics_fee_inputs.py` (9 passed)
    - Effective schedule revisions `stt.2024-10-01` and `stt.2026-04-01`, exercise/assignment STT and broker charges, contract-note integer paise rounding, missing broker fee blocking reconciled.
  - Task B2: `feat: evaluate verified aggregate compliance inputs` (commit `1dcd3e0`)
    - Files: `quant_compliance.py`, `tests/test_remaining_compliance.py`
    - Tests: `tests/test_remaining_compliance.py` + `tests/test_analytics_compliance_inputs.py` (12 passed)
    - Stock MWPL vs index derivative exemption, underlying multi-contract aggregation, sign reversal and intraday exposure increases, NCL/CMPT/64639 expiry ELM effective dates, NCL/CMPT/66047 and 72906 calendar spread cutoffs, missing SPAN component preservation.
  - Contract Cherry-pick: `feat(analytics): establish remaining source risk handoff contract` (commit `cc04640`, upstream `2c83b88`)
    - Files: `analytics_remaining_contracts.py`, `tests/test_analytics_remaining_contracts.py` (5 passed)
  - Task B3: `feat: evaluate combined captured account proposal risk` (commit `cced193`)
    - Files: `analytics_remaining_risk.py`, `tests/test_remaining_account_risk.py`
    - Tests: `tests/test_remaining_account_risk.py` (5 passed)
    - Evaluates `CapturedRiskBundle` with optional `StrategyProposal`. Single-pass position netting, cross-evidence/future contradiction rejection, stress matrix repricing over combined inventory, separate gross/net metrics, partial coverage preservation.
  - Task B4: `feat: reconcile portfolio cash flow performance` (commit `2264716`)
    - Files: `quant_attribution.py`, `tests/test_remaining_attribution.py`
    - Tests: `tests/test_remaining_attribution.py` + `tests/test_analytics_attribution_inputs.py` (15 passed)
    - Cash-flow-adjusted returns (deposits/withdrawals do not distort returns), trade inventory cash reconciliation with realized PnL and fees, short-history independent drawdown metric preservation, missing-benchmark selective alpha/beta disabling.
  - Task B5: `test: verify independent tail and stress acceptance` (commit `3433a3a`)
    - Files: `tests/test_remaining_tail_acceptance.py`
    - Tests: `tests/test_remaining_tail_acceptance.py` (4 passed)
    - Acceptance tests for scenario counts (249, 250, 999, 1000), 95% available when 99% missing with exact reason `insufficient_history_for_99pct`, 28-cell stress grid independence, non-finite / duplicate / inverted scenario rejection.
  - Task B6: `test: add independent remaining analytics evaluations` (commits `72f3869` & `f875479`)
    - Files: `evals/analytics_router_remaining.v1.json`, `evals/remaining_live_evals.py`, `tests/test_remaining_eval_guards.py`
    - Tests: `tests/test_remaining_eval_guards.py` (5 passed)
    - Live model flag enforcement, sanitization (no private tokens/secrets in output), turn budget constraint (<=2 MCP calls per turn including prefetch), proposal selection without lookup calls, continuation session invalidation.

## Test Verification Summary
- B test files suite: `pytest tests/test_remaining_*.py` -> 30 passed in 1.09s
- Full combined analytics & remaining suite: 61 passed in 9.78s
- Offline eval replay: `remaining_live_evals.py --dry-run` -> 12/12 PASS
- Contract replay: `analytics_evals` -> 20/20 PASS
- Dependency check: `pip check` -> clean (no broken requirements found)

## Handoff to Part A
Owned commits on `codex/agents-remaining-b`:
- `6adcd95`: feat: reconcile dated complete cost schedules
- `1dcd3e0`: feat: evaluate verified aggregate compliance inputs
- `cc04640`: feat(analytics): establish remaining source risk handoff contract (cherry-pick 2c83b88)
- `cced193`: feat: evaluate combined captured account proposal risk
- `2264716`: feat: reconcile portfolio cash flow performance
- `3433a3a`: test: verify independent tail and stress acceptance
- `72f3869`: test: add independent remaining analytics evaluations
- `f875479`: fix(evals): ensure path resolution when remaining_live_evals invoked directly

No capture, provider, or adapter files were modified. Part A can cherry-pick or merge these owned commits.
