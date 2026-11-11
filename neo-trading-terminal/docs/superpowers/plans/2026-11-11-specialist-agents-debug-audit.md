# Specialist agents: debugging audit and remediation

Reviewed baseline: `0047dc4`, 11 November 2026. The findings below describe that baseline. Remediation has now been applied in the working tree as documented at the end.

## Verdict

The specialist factories, tool-restricted projections, master route, history contracts, offline evaluator and handoff exist. Do not mark every heavy-core requirement complete: shared admission and trace completeness still diverge from the plan. Offline tests do not establish live routing accuracy, prose factual accuracy, or local-model readiness.

## Findings

### High: admission is split across routing and explicit requests

`unified_chat.py:dispatch_unified` enters `service.routing_limiter`; `options_agent.py:_chat` independently enters `self.active` and `self.recent`. Both have separate locks/counters. A route can run while the same owner's explicit chat is active. Four routing users and four explicit users can consume provider capacity concurrently. Delegation subsequently consumes a second admission rather than inheriting one parent admission. Clarification and direct requests also count against separate per-minute histories.

Fix in `unified_chat.py`, `options_agent.py`, and their routing/harness tests: centralize admission in a service-owned parent lease, inherited by the trusted delegated specialist. Preserve snapshot capacity and retain capacity while shielded synchronous work completes. Do not trust client-supplied bypass flags.

Required regression tests: block explicit model execution, start Auto for the same owner and assert no router invocation; reverse the order; mix users across both entry points and reject the fifth; mix clarification/explicit calls and reject the seventh in one minute; ensure delegation consumes exactly one admission; cancellation must not release pending worker capacity early.

### Medium: configured backup-key retry conflicts with conservative usage accounting

`agent_harness.py:bounded_invoke` accounts every provider exception as unknown usage, retaining the full reserved stage allowance. `BoundedOpenAIChat.ainvoke` and `BoundedGemini.ainvoke` then attempt backup-key rotation after HTTP 429, but the next reservation finds no generation allowance. This follows the current unknown-usage policy, yet makes fallback ineffective under the production harness. It must be reconciled explicitly, not fixed by refunding every failed call.

Add production-harness tests around both real adapter classes with mocked SDK transport: 429 followed by success, unknown transport failure, cancellation, partial generation, and attempt exhaustion. Define which provider rejections can reliably prove no generation occurred. Only those may refund generation reservation; all attempts remain charged and unknown outcomes remain conservatively charged. Otherwise document fallback as unavailable when usage is unknown and preserve the original quota error rather than obscuring it as budget exhaustion.

### Medium: production traces omit planned accounting fields

`RequestHarness.reserve` receives input estimates but does not retain them. `trace()` contains attempts, generation, duration and tool reads, but lacks input estimate values, broker/cache counts, and explicit delegation counts. Specialist SDK usage is recorded separately, but cannot supply missing request estimates or broker/cache events.

Implement numeric allowlisted fields in `agent_harness.py`; instrument actual events in `options_mcp.py` and routing. Record estimates separately from actual provider usage, including availability. Test cache hit versus fetch, tool prefetch versus requested read, failed calls, redaction, and parent/child aggregation without double-counting. Do not put evidence or provider bodies into trace data.

### Part 2 prerequisite: structured scope-change errors are not exposed by the UI client

`frontend/src/lib/api.ts:30` keeps `detail` only when it is a string. The backend's structured 409 code becomes generic `Request failed (409)`. The current chat page also lacks the specialist/Auto integration. This is expected unfinished Part 2 work, not evidence that backend risk routing is absent. Add `src/lib/api.ts` to Part 2 ownership and preserve status/code on the client error. Test draft preservation and no automatic resubmission.

### Code quality observations

The parent trace writer catches storage exceptions and silently ignores them; the caller marks the trace persisted before knowing whether storage succeeded. Add a sanitized diagnostic/counter for trace write failures and test it without changing successful answer persistence semantics. Dense one-line statements and broad exception handling make lifecycle code harder to review; prioritize small behavioral fixes above wholesale formatting.

## Execution order

1. Reproduce admission overlap with blocked asynchronous calls; implement a shared lease and rerun API/routing/cancellation tests.
2. Resolve retry accounting with provider-specific evidence and adapter regression tests.
3. Complete sanitized trace accounting and failure diagnostics.
4. Refresh handoff completion claims and add the API client file to Part 2's implementation scope.
5. Run full backend tests, offline evaluators, frontend tests/lint/build. Record exact results and skipped tests. Live provider/broker runs require explicit opt-in.

## Documentation cross-check

Context7 retrieved Agno's route-mode documentation: `TeamMode.route` returns the selected member response directly, and `determine_input_for_members=False` forwards the input unchanged. The existing router uses those settings consistently. Reference: https://github.com/agno-agi/docs/blob/main/teams/delegation.mdx . This confirms configuration intent, not live classification accuracy.

## Fresh verification

- Backend dependency check: passed; environment reports an invalid leftover `~tarlette` distribution warning.
- Frontend tests: 71 passed.
- Frontend lint and production build: passed.
- Specialist offline evaluation: 18/18 passed; model_evaluated=false.
- Full backend suite: 651 passed, 2 skipped, 2 pytest cache permission warnings in 275.57 seconds. Cache warnings did not fail tests. Skipped tests are not counted as verified behavior.
- Catch-all search: zero matches for the old registration or `build_agent(` across backend app/tests.
- Harness reproduction: retaining a 900-token unknown-usage reservation makes the next reservation raise `HarnessError('model_budget')`.

Scope limitation: reviewed the specialist integration and its shared runtime boundaries, ran repository regression checks, and examined the supplied reports. This is not a line-by-line audit of every unrelated trading subsystem, nor a guarantee that all defects have been found.

## Applied remediation

- Routing admission now shares the explicit request's lock, active owners, recent admissions, and refresh capacity. Delegated specialists inherit the trusted parent harness admission, consume no second admission, and leave release to the parent. Pending worker release uses the existing cancellation-safe service lifecycle.
- Explicit provider HTTP 429 rejection refunds its generation reservation while still consuming an attempt; unknown transport failures and cancellation retain the reservation. A production OpenAI adapter regression exercises primary-key rejection followed by successful backup-key invocation under the parent harness.
- Traces retain cumulative input estimates, delegation counts, snapshot-service fetch attempts and request-local cache hits. These fetch counts represent snapshot-service calls, not individual broker HTTP requests hidden inside that service.
- Trace storage exceptions emit a fixed sanitized warning without exception contents.
- The API client exposes `ApiError.status` and `ApiError.code` and preserves the structured scope-change message. The full specialist-selection UI remains Part 2.
- Retired the unused combined portfolio-agent contract (`PortfolioAnswer`), its mixed portfolio instructions, and `make_scope()`. Snapshot runs now identify themselves as `snapshot.chain.1` or `snapshot.portfolio.1`; specialist chat continues to use the separate analysis/risk contracts. Historical stored conversations remain readable and fail closed on attempted continuation.
- Added backend admission, retry, cancellation-retention and trace-warning regressions; MCP tests assert fetch/cache counters. Added a frontend structured-409 regression.

Post-fix frontend: 72 tests passed; lint and production build passed. Backend full suite: 653 passed, 2 skipped in 276.61 seconds with pytest caching disabled to avoid the existing cache-directory permission warning. The final five audit regressions also passed separately; three were added after the full run collected tests. MCP plus audit regressions passed separately (13 tests at that point). No live provider or broker calls were used.
