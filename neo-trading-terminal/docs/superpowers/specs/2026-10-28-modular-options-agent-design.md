# One agent, modular services, private MCP

Status: approved by the user on 2026-10-28; proceed to the Phase 1 implementation plan.
Date: 2026-10-28.
Builder check: independent reviewer found no important unanswered questions for
planning Phase 1. Product implementation has not started under this design.

## Intent and scope

Extend the existing signed-in options chat into an auditable assistant for broker
portfolio data, monitoring, strategy analysis and opportunity discovery. One Agno
agent interprets questions and explains results. Python services retrieve and
validate evidence, calculate values and enforce risk policy. A private MCP server
exposes only the capabilities authorized for the current request.

This document fixes the architecture and defines the next delivery milestone,
Phase 1. Later phases below are a roadmap, not authorization to implement every
strategy, scanner, alert or backtest now. Phase 0 provider integration is complete
in code; live provider quality, quota and broker connectivity remain separate checks.

## Approaches and decision

1. **Selected: one agent, modular services, private MCP.** Reuses the existing
   FastAPI process, Agno integration, loopback listener, user sessions and SQLite
   evidence. Gives each calculation and tool a small, independently testable scope.
2. **Deferred: separate strategy, scanner and risk agents.** Useful if independent
   research workflows later justify coordination overhead, but introduces more
   model calls, context transfers and failure paths now.

The user selected approach 1. The agent runs in the backend and calls MCP; the
MCP server hosts tools and service adapters. Modules are initially Python modules
in the same process, not separately deployed services. Keep one backend worker
while broker sessions and execution limits are process-local.

## Current foundation and gaps

- `options_agent.py`: authenticated execution, bounded model runs, structured
  answers, conversation ownership and sanitized run records.
- `options_mcp.py`: private Streamable HTTP, expiring request capabilities, cached
  immutable evidence and one no-argument `get_option_snapshot` tool.
- `options_snapshot.py`: option-chain validation and deterministic OI calculations.
  Bid/ask, IV, Greeks and exchange timestamps are currently unavailable.
- `portfolio.py`: user-specific holdings, positions, funds and orders with caching.
  Some missing inputs default to zero or one, unknown order sides become SELL,
  and instrument matching can remain unresolved. These paths need explicit data
  quality handling before they become agent evidence.
- `risk.py`: existing order limits and kill switch. These are execution controls,
  not yet the proposed portfolio risk engine.

Existing website execution routes are not registered as MCP tools. Existing
conversation and API contracts must remain usable throughout the expansion.

## Responsibilities

| Component | Responsibility |
|---|---|
| Website and authenticated API | User identity, explicit chat scope and market selection |
| Agent runner | Select authorized tools, bound context/work, validate evidence references |
| Private MCP | Enforce capability scope and tool access on every invocation |
| Broker adapter and snapshot services | Fetch, normalize, reconcile and label evidence |
| Calculation services | Deterministic P&L derivations, payoffs, yields and exposure |
| Risk service | Evaluate versioned policies and report breaches or inability to assess |
| Agno model | Explain evidence, limitations and calculation results in natural language |
| Evaluation and audit | Reproduce calculations, test model behavior and retain provenance |

The model must not estimate missing numerical inputs or edit policies. A future
risk result has three explicit outcomes: pass, breach, cannot_assess. Missing
data cannot be interpreted as a passing risk check.

## Phase 1: reliable broker evidence

### Deliverable

A signed-in user can ask about their holdings, positions, orders and available
broker funds through the same agent. Every answer identifies the evidence used
and its data limitations. Existing option-chain chat continues to operate.
This milestone does not provide strategy suitability, background alerts or risk
recommendations; those depend on the validated evidence built here.

### Data contract

Introduce a versioned portfolio snapshot with a generated evidence ID, source,
retrieval start/end times, per-section retrieval times, provider timestamps when
available, cache age, completeness and explicit limitations. Account ownership
is internal metadata; no model-supplied user ID is accepted.

Each section (holdings, positions, orders, funds) has an explicit state:
available, partial, unavailable or invalid. A successful empty response is an
available empty section. A failed request is an unavailable section, never an
empty account. Row-level malformed data must remain visible through an issue
record and affected aggregates must be unavailable rather than silently omitting
the row. Authentication expiry fails the entire retrieval.

Preserve zero when the provider supplied a valid zero. Reject boolean, nonfinite
and invalid numeric inputs. Missing quantities, multipliers, costs and order
sides stay unknown. Derive a value only when all required inputs are valid and
record the formula version and input references. Negative values are allowed
where domain-appropriate, such as short position quantities and P&L.

Normalize instrument identity using exchange, token, symbol, contract type,
expiry, strike and lot size where available. Contradictory identities invalidate
the affected row. Ambiguous matches remain unresolved and cannot be used for
strategy leg matching. Never infer an option contract using a symbol substring.

Provider P&L and calculated P&L are distinct fields with named bases. Do not sum
broker totals, holdings valuations and position MTM unless their definitions
and overlap are verified. Money arithmetic uses decimal values with documented
rounding and units; unknown FX or contract scaling blocks derived totals.

Collection is not an atomic broker snapshot. Preserve per-section timing and
label temporal inconsistency. Retrieval time alone is never exchange freshness.
Phase 1 labels unknown freshness; future strategy/risk services must apply an
explicit freshness policy before assessment.

### Service and API integration

Extract normalization from transport so synthetic broker fixtures can exercise
it without network or credentials. Reuse broker sessions and instrument catalogue.
Provide a compatibility adapter for the existing portfolio UI instead of changing
existing response fields in place. Add explicit quality fields where needed so
that UI totals and missing-data labels remain truthful.

Keep `/api/options-agent/chat` and its option snapshot contract unchanged. Add
portfolio-specific snapshot/chat entry points under the same API router, backed
by the same runner with a trusted scope parameter. Portfolio requests require
no unrelated option-chain fetch. The UI provides explicit chain/portfolio scope;
switching scope starts a new conversation. The model cannot change scope.

Portfolio answers use a versioned evidence-reference contract and a portfolio
snapshot field. Do not overload the existing chain `snapshot_ids` field with
portfolio IDs. Store versioned evidence additively in existing conversation/run
storage or new tables; old records remain readable and owner-scoped.

### MCP changes

Add a no-argument `get_portfolio_snapshot` tool. Extend capabilities with an
explicit allowed-tool set and scope. Chain requests authorize only the chain
tool; portfolio requests authorize only the portfolio tool. Enforce this in the
server tool handler or authorization middleware even for direct protocol calls.
Filter discovery accordingly. Agno's `include_tools` remains a convenience,
not the permission boundary.

Each request prefetches exactly one scoped snapshot through MCP and uses that
same immutable snapshot for model evidence, subsequent tool reads and displayed
figures. Cache keys include authenticated user, session generation and scope.
Logout, reconnection or account changes invalidate relevant caches. Successful
evidence remains immutable; a refresh creates new evidence.

Preserve existing limits: one active chat per user, six attempts per minute,
four active options requests globally, two agent tool calls, at most three model
requests, 30-second model timeout and 60-second overall deadline. Broker calls
remain outside the event loop with bounded network timeouts. Retain execution
capacity until a synchronous broker operation really finishes after cancellation.
Portfolio retrieval may make several broker calls, so test its aggregate deadline
and partial-result behavior rather than multiplying timeouts unnoticed.

### Phase 1 acceptance criteria

1. Authenticated portfolio chat -> Agno -> real MCP protocol -> controlled broker
   fixture -> validated answer works; unrelated chain data is not required.
2. Empty account, zero quantity and missing quantity are distinguishable.
3. Malformed prices, unknown sides, missing multipliers, invalid denominators,
   ambiguous contracts and failed individual sections produce explicit limitations.
4. Provenance distinguishes provider values, derived values, cached observations
   and unknown exchange freshness. Known fixture arithmetic matches independent
   expected values and decimal rounding.
5. Cross-user access, cross-scope tool calls, expired/revoked capabilities and
   stale-session cache reuse fail. Conversation ownership remains enforced.
6. Timeouts and cancellations retain broker capacity correctly; failed turns are
   not saved as successful answers. Logs exclude secrets and raw broker errors.
7. Existing portfolio UI and options-chat tests pass; late responses from a prior
   scope/selection are ignored, and errors preserve clearly labelled old evidence.
8. Offline protocol/calculation checks, opt-in model evaluations and explicit
   live broker smoke checks report separate outcomes.

## Later milestones

### Phase 2: monitoring and portfolio risk

Build deterministic concentration, expiry exposure, margin utilization and P&L
checks from validated snapshots. Drawdowns need a defined equity history and
cash-flow treatment, so cannot be inferred from one current snapshot. Configure
risk thresholds through authenticated settings, with versions and audit records.
Users must choose substantive limits; the model cannot invent or override them.

Start with visible-page monitoring. A later background scheduler requires its
own durable user-scoped jobs, session-expiry handling, deduplication, workload
limits and restart behavior. Refresh data and evaluate risk in code without a
model call per price update. Specify notification destinations before alerts.

### Phase 3: covered calls and collars

Build deterministic eligibility, matched-leg payoff, cost, capital and scenario
calculators. Use validated contract metadata, settlement rules and broker funds/
margin evidence. Show the capital basis and horizon for every yield. Do not label
premium received as total profit or a guaranteed return. Retain the starting
strategy assumptions and explicit leg associations for later deviation checks.

Proposed first scope: analyse positions already owned. Whether to add new-stock
purchase proposals remains a user decision before this phase; it does not block
Phase 1. The agent explains calculations and failed eligibility checks. It gains
no order-placement, cancellation or risk-policy editing tools.

### Phase 4: scanner

First validate quote depth, spread, liquidity, volatility inputs and universe
coverage. Apply eligibility and risk filters before ranking. Run bounded scans
in deterministic jobs, not a model-driven loop over every contract. Return
transparent scores, assumptions, excluded candidates and reproducible evidence.
Specify the investment universe, yield definition and ranking weights before
implementation. Data licensing and API quotas are feasibility constraints.

### Phase 5: backtesting and performance

Require point-in-time contracts, corporate actions, delistings and usable quote
history. Model costs, slippage, partial fills, settlement and liquidity limits;
prevent future-data leakage. Use the same versioned strategy calculations as the
live analysis. Historical data availability must be established before promising
coverage. Compare expected and realized results using stored strategy baselines.

## Evaluation and fine-tuning research

Begin an evaluation workstream with Phase 1. Use synthetic fixtures initially;
historical/live samples require explicit capture rules, data rights, redaction
and ownership. Keep development examples and a held-out benchmark separate.

Evaluate factual accuracy, numeric correctness, traceability, completeness,
consistency, missing versus zero, financial interpretation and abstention. Include
stale/partial/conflicting data, injection attempts, cross-user requests and
unsupported orders. Independently validate expected numeric answers; do not use
the tested model to create its own answer key. Combine deterministic checks with
human review of model prose. Structured output alone is not proof of correctness.

Track rubric and dataset versions, provider/model, prompt/tool/calculation
versions, failures, latency and usage/cost where available. Run regression checks
before promoting model or prompt changes. Determine measured score thresholds
before enabling strategy recommendations. Existing isolation, execution and
deterministic arithmetic tests remain hard release gates.

Compare the base model with improved prompts, curated context and structured
tools first. Consider fine-tuning only for persistent measured deficits, using
the same held-out benchmark. No autonomous training or deployment is part of this
design. Free-tier quota availability does not guarantee uninterrupted operation.

## Decisions left to implementation and approval

- The builder may choose module names, internal dataclasses and test layout while
  preserving contracts, ownership, precision and existing behavior.
- Existing holdings first is a proposal for Phase 3, not a user-approved scope.
- New strategy/risk policies and historical data sources need later specifications.
- Approval of this document permits a detailed Phase 1 implementation plan; it
  does not mark future capabilities as implemented or their live checks as passed.

## Sources and durable project record

Current code and `docs/OPTIONS_HARNESS_PROGRESS.md` are the implementation baseline.
Context7 lookup on 2026-10-28 confirms FastMCP can check authorization on discovery
and invocation; the implementation must verify APIs against the pinned version:
https://github.com/prefecthq/fastmcp/blob/main/docs/servers/authorization.mdx
https://github.com/prefecthq/fastmcp/blob/main/SECURITY.md

Tree Ring Memory guidance was consulted. No local CLI/store was available at the
last check, so this document is the durable repository decision record; no memory
capture or synchronization is claimed. No credentials or account data are stored here.
