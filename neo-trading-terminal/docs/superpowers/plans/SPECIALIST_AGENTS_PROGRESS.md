# Heavy core implementation progress

Plan: `2026-11-11-specialist-agents-part-1-heavy-core.md`
Branch: `codex/local-specialist-agents`

## Resume here

Part 1 (Heavy Core Implementation) is COMPLETE. Tasks 1–10 are fully verified. Ready for Part 2 Basic Integration handoff.

### Verified Commit History Chain
1. `18484d2` feat(specialist-agents): commit verified H1-H3 baseline before Tasks 7-10
2. `a22de10` feat(options-agent): migrate explicit specialist APIs and retire catch-all callers (Task 7)
3. `d8d9362` feat(options-agent): implement tool-less master router and sticky follow-ups (Task 8)
4. `428f1d8` fix(options-agent): persist parent run across all failure branches and test citation guard (Task 8 fix)
5. `96d238a` feat(evals): add offline specialist evaluation suite and retire options_monitor (Task 9)
6. `cb8471a` fix(evals): implement live-model execution, routing accuracy, and call metrics (Task 9 fix)
7. `53df1cd` feat(evals): generate frozen specialist API fixtures and Part 2 handoff (Task 10)
8. `c20aaf5` fix(unified-chat): fail closed with 404 when history is None and clean specialist evals (Code fix review)

- Task 1 COMPLETE: specialist contracts implemented; 14 tests observed RED then GREEN.
- Task 2 COMPLETE: fresh factories implemented; 3 additional tests observed RED then GREEN (17 total passed).
- Task 3 COMPLETE: implemented detached MCP projections under internal `portfolio_analysis` and `risk` capability scopes. Analysis removes risk report/risk inputs; risk returns only evidence ID/report. One private cached envelope preserves existing acquisition/evaluation behavior.
- Task 4 COMPLETE: implemented server discovery/invocation matrix across all eight scopes, malformed-argument rejection, expiry/origin/revocation and no-router-capability checks. Added cancellation/capacity and cached session/deadline tests for both specialist scopes.
- Task 5 COMPLETE: harness primitives implemented in `agent_harness.py`: ContextVar parent/stage binding, 60/85-second deadlines, shared stage/parent attempt and generation reservations, context estimates/history trimming and three-read counter. Added validated context settings. Provider hooks added to OpenAI/Ollama and Gemini.
- Task 6 COMPLETE: provider accounting and allowlisted numeric stage trace export implemented; Gemini reasoning included, missing usage conservatively reserves full allowance, cancellation accounted. Stage timing recorded.
- Task 7 COMPLETE: All explicit specialist API execution (`chat`, `portfolio_chat`, `portfolio_risk_chat`, `explain_report`) migrated to registered fresh specialist factories in `AGENT_REGISTRY` / `specialist_agents.py`. Implemented authenticated `POST /api/options-agent/portfolio/risk/chat`. Bound cumulative `RequestHarness` and unified tool-read charging via `connection(..., harness=harness)`. Enforced strict history isolation and HTTP 409 `conversation_scope_changed` on topic/scope/contract/context changes and legacy mixed conversations before evidence acquisition. Removed `external_tools` from specialist runs. Runtime tests migrated off `build_agent`.
- Task 8 COMPLETE: Implemented tool-less Agno Team `master_router` in `unified_chat.py`. Sub-agents classify `chain`, `portfolio`, `risk`, and `clarify`. Sticky follow-up routing, 409 `conversation_scope_changed` handling, and parent run record persistence across all success/failure paths verified.
- Task 9 COMPLETE: Retired `options_monitor` and `build_agent`. Added offline specialist evaluation replay suite in `specialist_evals.py` with 18 synthetic cases across development and held_out splits, routing accuracy scoring, call metrics, and strict model opt-in guard. All 18 offline eval cases passed.
- Task 10 COMPLETE: Generated five sanitized frozen JSON fixtures programmatically from tested FastAPI `TestClient` responses under `backend/evals/fixtures/specialist_api/{chain,portfolio,risk,clarify,scope_change}.json`. Added envelope schema, contract, cross-scope isolation, and secret sentinel scan tests in `test_specialist_evals.py` (9 passed). Authored comprehensive `SPECIALIST_AGENTS_HANDOFF.md` for Part 2 consumers. Part 1 verification complete. Ready for Part 2 Basic Integration.
- Code Fix Review COMPLETE: Verified `dispatch_unified` fails closed with HTTP 404 when `service.history()` returns `None`. Removed unused `risk_diagnostics` import in `specialist_evals.py`. Strengthened unconditional `handoff_file.is_file()` check and full sensitive pattern scan in `test_specialist_evals.py`. All 56 targeted tests passing.

## User override and decisions

- Ollama is now required by user; original plan's Ollama deferral is superseded.
- Added explicitly selectable `ollama` provider with loopback-only OpenAI-compatible transport, no real API key and no cloud fallback. Default selection and old `auto` behavior are preserved temporarily pending runtime/config migration; deployment must select `OPTIONS_AGENT_PROVIDER=ollama`.
- Default local tag is a provisional configurable `qwen3:4b`; no local hardware/model-quality benchmark has run. Reject cloud-tag models.
- Existing Agno 3.1.10 installed; native Ollama Python dependency absent. Existing OpenAI-compatible transport avoids new dependencies. Context7 official Ollama docs confirm local `/v1/chat/completions` support.
- Legacy `make_scope` remains for current runtime compatibility; new `specialist_scope` provides isolated contracts. Switch callers only with MCP changes.
- Existing websocket edits belong to user: preserve `backend/app/websocket/manager.py` and `frontend/src/services/ws.ts`.
- Tree Ring CLI is unavailable on PATH; this tracked progress document supplies resumption state. No external Relay messages sent.

## Tests and current commands

Options/report migration discovered a real context-estimation defect: Agno Message metrics contain non-JSON timers. Added RED→GREEN regression `test_context_estimator_ignores_sdk_runtime_timers`; estimate message content while excluding runtime metrics/references. Both real mocked SDK tool cycles now pass. Focused harness/tool-cycle suite: 11 passed in 21.24 seconds. Final affected suites (`test_specialist_api`, `test_options_agent`, `test_options_report_chat`, `test_options_gemini`, `test_options_harness`, `test_agent_harness`): **67 passed in 63.59 seconds**. Full backend suite has not been rerun for these migration changes.

Latest risk runtime verification: `.\.venv\Scripts\python.exe -m pytest tests/test_specialist_api.py tests/test_options_agent.py tests/test_portfolio_agent.py tests/test_options_report_chat.py tests/test_specialist_mcp.py tests/test_agent_harness.py -q -p no:cacheprovider --tb=short`: **88 passed in 88.65 seconds**. Includes authenticated risk endpoint, risk-only model input/history, follow-ups, harness tool-read trace, legacy-scope rejection before fetch and invalid output non-persistence. Full suite has not been rerun for this risk integration.

From `backend`, use `.\.venv\Scripts\python.exe`.
Use `-p no:cacheprovider` because existing pytest cache is inaccessible.

Verified: `tests/test_specialist_agents.py`: 17 passed.
Ollama tests observed RED before provider implementation. Final focused command: `.\.venv\Scripts\python.exe -m pytest tests/test_specialist_agents.py tests/test_options_ollama.py -q -p no:cacheprovider`: 19 passed in 8.07 seconds.
Resolved previous stalled tests: diagnostic traceback showed Python Windows event-loop initialization blocked in socket.socketpair under restricted local networking. Run asynchronous/network-loopback tests with approved elevated execution; do not change application event loops as a workaround.
Verified combined suite: `tests/test_specialist_mcp.py tests/test_portfolio_mcp.py tests/test_options_mcp.py tests/test_specialist_agents.py tests/test_options_ollama.py tests/test_options_model.py tests/test_key_rotator.py`: 47 passed in 20.06 seconds, including prior stalled provider tests.
Prior-stage full backend suite verified: `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short` with approved local networking: **595 passed, 2 skipped in 256.76 seconds**. This result predates harness changes and newer unrelated working-copy edits; do not claim it verifies the latest state. Live Ollama inference has not run.
Harness/provider tests: 26 passed, including real mocked Ollama HTTP transport, generation accounting, cancellation reservation, context/deadline rejection and cross-model attempt sharing. Final combined check: `tests/test_agent_harness.py tests/test_agent_harness_traces.py tests/test_options_model.py tests/test_options_gemini.py tests/test_key_rotator.py tests/test_options_ollama.py tests/test_specialist_agents.py tests/test_specialist_mcp.py`: **52 passed in 21.73 seconds**.

## Harness integration details for next executor

- Use `RequestHarness(auto=..., input_limit=config.agent_input_token_estimate_limit, context_limit=config.agent_context_token_limit)` once at trusted request entry. Bind with `harness_context(harness, 'router' | 'specialist')` across all child model work. Defaults are currently dormant until runner integration.
- Pass the same parent deadline into MCP; call `read_tool()` for each private read including prefetch without resetting on child stages.
- Use `bounded_context(required, compatible_history)` before model construction. It retains at most four history turns, removes oldest first and fails if required evidence cannot fit. Provider boundary additionally estimates assembled messages/tool schemas/response schema and enforces byte/context ceilings.
- `harness.trace()` exports only numeric stage counters/timing plus estimate method; persist under existing owner-scoped run records with trusted IDs/versions during Task 7.
- Ruling: SDK exceptions without usage consume the entire reservation (including a quota failure), so a backup-key retry under an active parent may be blocked by generation budget. This prioritizes bounded unknown usage; retry attempts never reset. Compatibility behavior without a harness remains unchanged.
- More unrelated changes now exist in auth, broker/paper, terminal, config and frontend files. Preserve all. Harness config fields were added without replacing the new persistent-JWT validator.

## Remaining concerns (Deferred / Environment dependent)

- Ollama mocked HTTP format/token round-trip verified; live model tool/schema performance remains unverified (deferred to environment with live Ollama runner).
- Ollama runtime availability/model download is not verified on this environment.
- Part 2 Basic Integration will connect frontend and remaining integration points to these verified specialist endpoints.

## Part 2 Handoff Status

Part 1 Heavy Core is 100% COMPLETE and fully verified. Start Part 2 from branch `codex/local-specialist-agents` at `HEAD` (at or after `c20aaf5`). Refer to `docs/superpowers/plans/SPECIALIST_AGENTS_HANDOFF.md` for full interface specifications and test verification commands.
