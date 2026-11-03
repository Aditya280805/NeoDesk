# Phase 2: visible-page monitoring and portfolio risk

Status: proposed for approval. Architecture remains the approved one agent,
modular services and private MCP. Phase 1 is complete for offline implementation;
live broker connectivity and model-quality checks remain unverified.

## Outcome

The signed-in user can configure portfolio monitoring limits, refresh the
portfolio, inspect deterministic risk findings and ask the existing agent to
explain those findings. Monitoring refreshes every 60 seconds while the chat page
is visible, as implemented in Phase 1. Risk calculation runs without a model call
on refresh. The model is used when the user asks for an explanation.

## Approach

Extend the existing portfolio service with a pure risk evaluator and a versioned
policy store. Retain the current read-only private MCP boundary. Background jobs,
notifications, order enforcement and strategy recommendations require later work;
this milestone reports observations and limits for user review.

A separate risk agent would add model calls without improving deterministic
checks. A background monitoring service would require durable jobs and broker
session renewal before it could reliably operate. The selected visible-page
approach follows the approved Phase 2 roadmap.

## Evidence and risk contract

Each risk report carries its own ID, the exact portfolio evidence ID, policy
version, calculation version, evaluation time, observation times and limitations.
Each finding includes check code, scope, outcome, measured value, unit, configured
limit, affected row IDs and safe explanation of unavailable inputs.

Checks return `pass`, `breach` or `cannot_assess`. Unconfigured limits yield
`cannot_assess` with reason `limit_not_configured`; no financial limit is invented.
Missing, partial, conflicting or insufficiently fresh inputs cannot yield a pass.
An observed breach can be reported even if unrelated inputs are unavailable,
with coverage limitations (for example, a known open position expiring today).
A ratio with an incomplete denominator cannot establish a breach or pass.
Stale financial observations cannot establish current financial outcomes.
Report summary precedence is breach, then cannot_assess, then pass among enabled
checks; all-disabled yields cannot_assess. Disabled checks remain in coverage.
A pass describes only named, evaluated checks, never overall safety.

Continue exact decimal arithmetic and decimal-string JSON. Compare limits with
unrounded values; round only for display. Do not sum holdings and positions into
an account total because they can overlap. Do not treat option premium value as
underlying exposure or infer Greeks.

## Initial checks

| Check | Calculation and prerequisites |
|---|---|
| Holdings concentration | Largest verified underlying holding value / complete positive eligible holdings value. Group identical verified identities; report this as holdings concentration, not whole-account concentration. Missing rows, unknown grouping or incomplete valuations block pass. |
| Expiry proximity | Identify nonzero derivative positions with verified expiry within the user's configured calendar-day window, using Asia/Kolkata dates. Include expired-but-open positions separately. Never assume an unknown expiry is distant. This is an expiry warning condition rather than a capital-loss estimate. |
| Margin utilization | Used margin / documented broker total margin basis, compared with a configured maximum percentage. If a compatible denominator is absent, return cannot_assess. Do not assume available cash plus used margin is the broker's denominator. |
| Loss limit | Compare a documented, non-overlapping broker P&L measure with a user-defined limit for that same basis and period. If basis/period is unknown or unsupported, return cannot_assess; holdings cost-to-current loss is not automatically daily loss. |
| Data quality | Surface missing sections, unresolved identities, cached observation age, non-atomic collection and unknown exchange freshness alongside each affected check. |

Drawdown is explicitly unavailable until a defined equity history, external cash
flows and benchmark period exist. Maximum strategy loss, portfolio Greeks,
scenario losses and strategy-wise yields depend on later calculation services.

## Freshness policy

Policies distinguish maximum observation age from exchange freshness. Unknown
exchange freshness is always displayed. Initially, exchange-sensitive margin and
loss checks cannot pass without the required source-time evidence. Holdings and
expiry checks may evaluate a recent REST observation with a permanent warning
that it is an observation-level check, not verified exchange-live analysis.
Observation age is calculated from original section times, including cache hits;
manual refresh must continue bypassing the cache.

## Policy settings

Add authenticated user-owned settings for concentration percentage, expiry window
days, margin utilization percentage, loss amount/basis/period, and maximum
observation age. Numeric risk thresholds start unset. Each check can be disabled
explicitly; disabled checks are displayed as not assessed and are not silently
removed from the coverage summary.

Policies have immutable revisions, created time and owner. Updates require the
expected current revision to prevent lost edits; invalid ranges, nonfinite or
boolean values, and unsupported loss bases are rejected. The settings UI explains
units and denominator requirements. The agent receives policy values as evidence
and cannot write settings. Existing manual order limits and kill switch continue
to have their own settings and enforcement semantics.

## Service, MCP and website

Create a pure `evaluate_portfolio_risk(snapshot, policy, as_of)` service, isolated
from broker, model and database access. Store policies and reports additively in
SQLite with authenticated owner checks and safe audit events.

The existing no-argument `get_portfolio_snapshot` returns the snapshot plus an
additive risk report. Bind one policy revision and immutable report to each run;
all repeated tool reads and displayed figures reference that same evidence.
Existing chain replies and old portfolio history remain readable. A policy edit
does not rewrite past reports; show the evaluated policy revision in history.

Add policy controls and a risk panel to portfolio chat. Show measured value,
limit, outcome, evidence time, affected positions and unavailable-data reasons.
Stop monitoring on errors, pause hidden-page refresh, invalidate late results
after a scope/session change, and retain clearly labelled prior evidence on
refresh failure. Explanations must cite the evaluated report and portfolio IDs.

## Harness and acceptance

- Pure fixture tests cover exact threshold equality, breach boundaries, zero
  denominators, duplicate instruments, long/short positions, missing expiry,
  expired positions, date rollover in Asia/Kolkata, stale observations and partial
  broker sections. Equality at a maximum limit passes; exceeding it breaches.
- Test policy ownership, revisions, concurrent edits, immutable history and
  rejection of model attempts to change limits or place orders.
- Real offline MCP/API tests preserve Phase 1 tool scope, immutable evidence,
  generation fences, cancellation, deadlines, model budgets and sanitized traces.
- UI tests cover configured/unconfigured checks, partial assessment, failed
  refresh, hidden pause and late replies. Refresh itself must make no model call.
- Extend held-out evaluations to financial explanations and abstention. Distinguish
  deterministic fixture checks from real model behavior and real broker access.
- Retain full backend/frontend/build gates and independent subagent review.

## Decisions and follow-up

This draft proposes configurable, initially unset risk limits. The user can enter
their own limits in authenticated settings after implementation. No substantive
financial thresholds are proposed as safe defaults.

The requested improvement review is recorded in
`docs/superpowers/plans/2026-10-29-portfolio-risk-phase-2.md`, pending user review.
Retain the selected subagent-driven execution method. Future scheduling, alerts,
strategies and backtesting remain separate milestones.

## Review refinements — 2026-10-29

- Add optional verified underlying grouping and typed margin/P&L basis, period,
  currency and timestamp metadata. Existing contract verification and generic
  provider provenance do not prove these semantics. Unsupported mappings remain
  absent and are displayed as unavailable.
- Financial settings and maximum observation age start unset. Validate decimal
  strings explicitly; reject boolean/coerced/oversized settings. Compare ratio
  thresholds by cross-multiplication before display rounding.
- Bind a policy revision at admission, persist immutable report references and
  label older-policy reports after a concurrent settings edit. Never rewrite
  historical findings. Policy PUT uses optimistic concurrency.
- Make empty, disabled and partial coverage explicit; no all-disabled green
  summary. Reject future/naive time evidence for affected checks and retain
  original cache observation times.
- Keep successful reports once, referenced by history, with a dry-run-first
  maintenance path that preserves referenced evidence. Separate operational
  evaluation failures from valid risk breaches in sanitized diagnostics.

These refinements tighten the proposed scope; they do not add execution or
background monitoring. No Phase 2 product implementation has started.

Context7 checked Pydantic Decimal and nullable-field validation guidance on
2026-10-29: https://github.com/pydantic/pydantic/blob/main/docs/migration.md
Implementation must use the pinned installed version. Tree Ring CLI/store was
unavailable at this check; this repository document records the design, with no
claim of memory capture or synchronization.
