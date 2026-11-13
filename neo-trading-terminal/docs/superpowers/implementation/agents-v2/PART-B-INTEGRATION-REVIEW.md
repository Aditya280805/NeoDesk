# Part B integration review

Integration update: owned B commits cherry-picked (excluding duplicate contract cc04640) as4090af3,5c0ebab,692f772,1131261,908c67e,17c0b15,086d697,a646584. Local correction pass removes invented proposal marks/expiry, requires explicit evidence binding and captured per-leg pricing, uses exact ACT365 timestamps, preserves unavailable FutEq/net costs/margin, and never defaults missing stress to zero. Removed inverse-variance allocation mislabeled as HRP. The B eval runner now actually calls classification in live mode and labels dry-run rows FIXTURE_ONLY with zero model passes.

Fresh reviewer identified further issues: incomplete aggregate FutEq inputs treated as zero, already-aggregated values double-counted, mixed-instrument trade pooling and missing opening inventory/fees, missing exercise costs included in totals. Corrections conservatively refuse unsupported inputs and keep missing totals unavailable. These are partial calculators, not proof of complete source coverage. A6 evaluator mounting remains deferred until trusted source bundle construction is implemented. Do not claim full task complete.

Reviewed branch codex/agents-remaining-b at4b175b9 against main97f55c2. User supplied completion report is not sufficient acceptance evidence. No Part B commits integrated yet; preserve both worktrees.

Blocking findings in analytics_remaining_risk.py:
- New proposal legs synthesize spot from strike, forward from spot, IV0.20, rate0.07 and expiry15:30 UTC. These violate the approved actual-expiry/verified-pricing and missing-data requirements. Require exact captured per-leg inputs; reject/mark missing otherwise.
- Aggregate FutEq is sum of raw contract quantities across instruments/underlyings. This is not delta-equivalent exposure and cannot establish limits. Require verified deltas, multipliers, underlying grouping and unit basis.
- Stress exceptions become None; missing worst_case_scenario defaults to0.0. Missing/failed risk must never become zero loss. Use actual quant_risk stress result contract and explicit unavailable metrics.
- Proposal timestamp check does not establish evidence-ID binding. Require immutable server-bound proposal/input identity from orchestration, not just valuation date.
- Option tau truncates actual timestamps to calendar dates and inserts0.0001 floor. Preserve ACT365 exact actual-expiry timestamps, reject expired series as appropriate.

Integration sequence: cherry-pick owned calculation/test commits only after review/fixes; skip cc04640 (duplicate of2c83b88 and would overwrite A1 follow-ups). Never replace A's private contract with B's older copy. Run newly failing regressions for each finding, corrected B tests plus all affected existing suites, then full backend and real guarded evals. Offline dry-run12/12 is not actual model quality.

Part A source gaps A2–A5 and final A6 integration remain independent unfinished work; do not mark complete because B report says complete. Exact authoritative dated fees/margins and real adjusted histories still need source verification.
