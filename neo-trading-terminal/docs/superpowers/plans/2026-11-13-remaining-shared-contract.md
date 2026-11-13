# Remaining implementation — shared handoff contract

Baseline: ca806c1, branch codex/local-specialist-agents, 2026-11-13.
Spec: ../implementation/agents-v2/PLAN.md and COMPLETION-GAPS.md.
This document supersedes stale source-cache statements in those files: the official dated NSE ban parser, bounded fetch, risk evidence mounting and five-minute exact-date cache are ALREADY implemented. Do not redo them.

## Checkout setup and ownership
Use two checkouts of the SAME repository at ca806c1, not unrelated codebases. A separate chat in the same checkout does not isolate edits. Do not copy the current dirty tree into the second checkout: it contains concurrent provider changes.
Suggested clean second worktree, run from repository root:
git worktree add -b codex/agents-remaining-b ../TRADING-agents-b ca806c1
First verify that directory and branch do not already exist. Copy only these three planning documents to the second checkout because they are newer than the baseline; do not copy .env, credentials, SQLite databases or logs.
Part A stays in the existing checkout; B must not restart A's signed-in backend. A owns all existing capture/source/portfolio files; B owns the explicitly listed numerical files and new risk modules. Do not stage someone else's files. Neither part owns existing uncommitted provider edits (.env.example, agent_harness, options_agent/model, specialist_agents, server/router and provider tests).

## Fixed integration contract v1
A creates backend/app/terminal/analytics_remaining_contracts.py.
Frozen Pydantic models, extra=forbid:
SourceStamp(source:str, revision:str, observed_at:datetime, effective_from:date|None, effective_until:date|None, checksum:str).
CapturedRiskBundle(owner_id:int, session_generation:str, as_of:datetime, positions:tuple[dict,...], rules:tuple[dict,...], fee_schedule:dict|None, account_coverage:Literal['complete','partial','unavailable'], missing_inputs:tuple[str,...], sources:tuple[SourceStamp,...]).
Timestamps must have timezones; owner positive and never inferred; dict fields are validated against existing input contracts before construction. positions/rules reuse normalized contracts in analytics_inputs.py, not raw broker payloads. Fees use integer paise and Decimal arithmetic.
B creates backend/app/terminal/analytics_remaining_risk.py:
evaluate_remaining_risk(bundle:CapturedRiskBundle, proposal:StrategyProposal|None=None)->dict
Pure function: no I/O, models, broker or MCP. Output keys: schema_version='remaining-risk.1', coverage, metrics, unavailable_reasons, source_refs, limitations. Reject identity/date contradictions. account_coverage is complete only when source coverage proves it, never because some sections loaded.
A calls this function from capture/handoff after B merges. Before B exists A uses explicit unavailable output; do not create a fake numerical implementation.
B may develop against a TEST-ONLY stub of the contract in its test fixtures; delete stub on integration and run against A's real model. B must not create a production duplicate.
A publishes contract commit hash first; B cherry-picks that isolated commit, then builds against the real contract. Avoid sharing live worktree files.

## Non-negotiable constraints
Read-only. No order/execution tools. Owner/session/policy/context-bound private capabilities; raw account envelopes never enter prompts/browser replies.
At most2 MCP invocations per specialist/foreground turn including prefetch,10seconds/tool,30seconds/turn. Candidate StrategyProposal IDs stay inside existing Options payloads; never add a proposal lookup call.
Independent historical tails:250–999 valid scenarios enables95% VaR/CVaR and only99% is unavailable with insufficient_history_for_99pct; >=1000 permits99%. Apply independently per series/horizon.
Continuation max2 resumptions,10minutes, idempotent and invalidated on session/policy/context/input changes.
Default rollout flags off. One public backend worker. Additive migrations. Unknown values stay unavailable.
Do not fabricate source schemas, fees, rates, expiry dates, limits, adjusted prices, or account completeness. Verify authoritative docs via Context7 where supported; exchange/broker primary publications otherwise. Record effective dates and revisions.
Do not push/deploy or perform transactions. Existing read-only live checks are authorized; new checkout must authenticate its own owner/session. Starting another backend must use an isolated port and test database.

## Known evidence and limits
Full backend812 passed BEFORE latest fetch/mount/cache additions. Latest analytics/quant166 passed; final cache source/capture20 passed after refresh correction. Do not describe this as a fresh full-suite result.
Canonical local live routing20/20; initial independent heldout9/10; fixed retest10/10 is regression evidence, not untouched heldout.
Signed-in UI: broker connected,159,551 catalogue entries, holdings/funds populated; positions/orders fetch_failed and holdings catalogue matching pending. Running backend predates latest commits; restarting loses broker sessions. No raw credentials/cookies copied.
Docker and gh CLI unavailable at last inspection. Official NSE source succeeded via PowerShell but Python urllib subsequently timed out. Empty-ban-day format unverified.

## Merge and final acceptance
Merge A's isolated contract first, then B's computational commits, then A's capture integration. Reconcile docs once at the end. Final full backend pytest + pip check + four offline eval modules; frontend tests/lint/build only if affected, then final browser verification. Run authenticated read-only source fixtures and independent live model evaluations separately. Remote CI/Docker are external gates, not reasons to invent local success.
Each part maintains its OWN status file with task, commit, exact tests, missing prerequisite and next file. Update after each slice; resume by reading that file and git log, not the entire chat.

