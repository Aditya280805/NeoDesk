# Heavy core implementation progress

Plan: `2026-11-11-specialist-agents-part-1-heavy-core.md`
Branch: `codex/local-specialist-agents`

## Resume here

Implementation is IN PROGRESS. Do not mark Part 1 complete or start Part 2.

- Task 1: specialist contracts implemented; 14 tests observed RED then GREEN.
- Task 2: fresh factories implemented; 3 additional tests observed RED then GREEN (17 total passed).
- Task 3: implemented detached MCP projections under internal `portfolio_analysis` and `risk` capability scopes. Analysis removes risk report/risk inputs; risk returns only evidence ID/report. One private cached envelope preserves existing acquisition/evaluation behavior.
- Task 4: implemented server discovery/invocation matrix across all eight scopes, malformed-argument rejection, expiry/origin/revocation and no-router-capability checks. Added cancellation/capacity and cached session/deadline tests for both specialist scopes.
- Task 5: harness primitives implemented in `agent_harness.py`: ContextVar parent/stage binding, 60/85-second deadlines, shared stage/parent attempt and generation reservations, context estimates/history trimming and three-read counter. Added validated context settings. Provider hooks added to OpenAI/Ollama and Gemini. Production request binding, admission consolidation and tool counter binding remain for Task 7.
- Task 6: provider accounting and allowlisted numeric stage trace export implemented; Gemini reasoning included, missing usage conservatively reserves full allowance, cancellation accounted. Stage timing recorded. Run-record persistence, complete failure-code mapping and router/specialist publication remain for Tasks 7–8.
- Tasks 7–10: pending. NEXT: read `options_agent.py` runner and `unified_chat.py`; integrate the new harness into admission/context/MCP/run records while migrating explicit APIs, then master router, eval migration and handoff.
- Runtime still uses the original factory intentionally until Tasks 3–8 are ready.

## User override and decisions

- Ollama is now required by user; original plan's Ollama deferral is superseded.
- Added explicitly selectable `ollama` provider with loopback-only OpenAI-compatible transport, no real API key and no cloud fallback. Default selection and old `auto` behavior are preserved temporarily pending runtime/config migration; deployment must select `OPTIONS_AGENT_PROVIDER=ollama`.
- Default local tag is a provisional configurable `qwen3:4b`; no local hardware/model-quality benchmark has run. Reject cloud-tag models.
- Existing Agno 3.1.10 installed; native Ollama Python dependency absent. Existing OpenAI-compatible transport avoids new dependencies. Context7 official Ollama docs confirm local `/v1/chat/completions` support.
- Legacy `make_scope` remains for current runtime compatibility; new `specialist_scope` provides isolated contracts. Switch callers only with MCP changes.
- Existing websocket edits belong to user: preserve `backend/app/websocket/manager.py` and `frontend/src/services/ws.ts`.
- Tree Ring CLI is unavailable on PATH; this tracked progress document supplies resumption state. No external Relay messages sent.

## Tests and current commands

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

## Remaining concerns

- Ollama mocked HTTP format/token round-trip now verified; live model tool/schema performance remains unverified.
- Ollama runtime availability/model download is not verified.
- New factories are loaded by importing `specialist_agents`; production registration/wiring is pending.
- Harden factory tests against forged scope contracts and actual tool naming restrictions with MCP tests.
- Parent harness, risk endpoint, history isolation, master router, evaluation migration and final handoff are all pending.

## Resume prompt

Read this file and the Part 1 plan. Inspect git diff. Re-run targeted tests, then continue Tasks 3–10 in dependency order. Honor the user's Ollama override and update this file after each verified task. Preserve user websocket changes. Never claim the old agent is removed until runtime and eval callers migrate.
