# Agent reply reliability: diagnosis and implementation plan

Date: 2026-11-13 (Asia/Calcutta)

## Scope and evidence

Reviewed the current, modified source in `C:/Users/Aditya Bose/OneDrive/Documents/TRADING`, branch `codex/local-specialist-agents`, HEAD `bbf18a9`. The chat's `b514` checkout is older and does not contain the agents. Implement against the current branch after reconciling its existing uncommitted work. This document does not change application code.

Read the live SQLite run table in read-only mode, inspected current source and installed Agno code, checked local Ollama tags and loaded-model status, and ran isolated existing tests. No model-generation evaluation, broker request, runtime restart, or production database modification was performed.

Today's persisted chat runs at inspection time:

| Scope | Completed | Failed |
| --- | ---: | ---: |
| Options | 2 | 15 |
| Portfolio analysis | 0 | 4 |
| Portfolio risk | 3 | 0 |

All 19 failed runs reached `output` after the model invocation and recorded `model_or_output`; none of these failures was recorded as a timeout. The latest options failure spent 53.39 seconds in the model and 54.09 seconds overall, with 2,046 output tokens. Portfolio failures took approximately 7.39–24.70 seconds overall. These are persisted outcomes from evolving runtime versions, not controlled measurements of the latest uncommitted source.

The configured Qwen model is installed and Ollama responds. `/api/ps` showed no model loaded at inspection time; this alone does not demonstrate a fault, but cold-load latency must be measured.

## Findings

### 1. Main observed problem: output rejection, with insufficient diagnostics

In `backend/app/terminal/options_agent.py`, `_chat` appends `output` immediately before `_validate_answer_content`. Failed runs never reached `publication`. The strongest supported localization is therefore response parsing/validation, rather than Ollama connectivity. Raw failed output and typed validation details are not retained, so the exact historical field/rejection cannot be established.

`_map_chat_error` and `options_model.provider_failure` collapse malformed JSON, schema violations, citation mismatches, and many provider failures into the same message. This prevents distinguishing configuration errors from a model answer rejected after successful inference.

### 2. Citation handling is inconsistent

`specialist_agents.py` binds options output to the captured snapshot via `bound_chain_answer.py`, but portfolio and risk use generic UUID schemas and prompt instructions. UUID validity does not enforce identity with current evidence.

There are also unreachable empty-list recovery branches in `_validate_answer_content`: `PortfolioAnalysisAnswer` and `PortfolioRiskAnswer` require at least one ID before those branches execute. A synthetic check confirmed empty `evidence_ids` raises Pydantic `too_short`; a different valid UUID raises `Invalid portfolio evidence citation`. This demonstrates concrete rejection paths, not proof that either caused every historical failure.

Options validation also rewrites certain incorrect contract-like citation strings into the current snapshot ID. Avoid expanding this permissive behavior; attaching a valid citation to arbitrary text does not prove that text used the correct evidence.

### 3. Streaming exists on the backend but is unused by the chat page

`frontend/src/pages/options-chat.tsx:ask` calls `/chat`, `/portfolio/chat`, `/portfolio/risk/chat`, or `/unified-chat` through the JSON API helper. It never consumes the specialist `/stream` endpoints. `OPTIONS_AGENT_STREAM=true` therefore does not make this page show live progress or tokens. A long inference appears as a static thinking message until final validation succeeds or fails.

### 4. Deadline policy conflicts

`OptionsAgent.deadline_seconds` and direct `RequestHarness` default to 60 seconds. The Ollama HTTP timeout defaults to 90 seconds. The JSON browser helper allows 120 seconds. Auto routing has an 85-second overall harness and a separate 25-second router ceiling. Increasing only `OLLAMA_TIMEOUT_SECONDS` cannot increase the specialist's actual 60-second ceiling. This is a latent failure risk; it does not explain the 19 observed output-stage failures.

### 5. Admission and cancellation need visible state

The service shares admission across specialists, snapshot refreshes, and pending broker work. Switching mode resets browser state but does not abort the existing fetch; another request can encounter 409/429 while the previous request still owns capacity. Retaining admission for genuinely running synchronous broker work is intentional and must remain.

## Ordered implementation plan

### Step 1 — Make failures identifiable

Files: `options_agent.py`, `options_model.py`, `agent_harness.py`, frontend `lib/api.ts`.

- Add typed failure codes for invalid JSON, schema violation, citation mismatch, empty output, generation truncation, model timeout, queue saturation, connection failure, context budget, and persistence failure.
- Record stage, safe exception class, allowlisted schema field/type, completion reason, token counts, and run ID. Never record prompts, account values, credentials, raw provider error bodies, or Pydantic input values.
- Preserve `X-Options-Run-Id` in `ApiError` and present actionable messages. Map harness timeout to timeout consistently instead of generic 503 budget failure.
- Confirm installed SDK completion-reason propagation before relying on it; add adapter capture if needed.

Acceptance: malformed JSON, empty citation list, wrong valid UUID, timeout, and overload produce distinct safe diagnostics in both JSON and SSE paths.

### Step 2 — Stabilize response contracts

Files: `specialist_agents.py`, `bound_chain_answer.py` or a shared replacement, `agent_scope.py`, `options_agent.py`.

- Extend request-bound citation schemas to portfolio evidence and risk report IDs. Preserve UUID parsing and final exact identity checks.
- Assert the actual OpenAI-compatible wire request contains the intended JSON schema for all three specialists, including tool-assisted turns and streaming.
- Use an explicit low-variance generation setting and concise answer instructions, then measure output quality rather than assuming a token-budget increase fixes validation.
- Remove unreachable recovery code and reject incorrect citations consistently. Do not expose unvalidated answers as final or silently relabel mismatched evidence.
- Permit at most one formatting/citation repair attempt only when the existing cumulative time/token/request budget permits it. Reuse the captured evidence; do not fetch a new snapshot or reset budgets. Otherwise return a specific failure and preserve access to the deterministic snapshot/report.

Acceptance: valid responses pass; malformed, empty, wrong-scope, stale-ID, and extra-field responses fail predictably; any repaired response undergoes the same validation. Existing account-isolation tests remain green.

### Step 3 — Expose progress and implement cancellation

Files: frontend `options-chat.tsx`, a dedicated SSE client module, frontend `lib/api.ts`, backend `routers/options_agent.py`, `options_agent.py`, and unified routing if extended.

- Connect direct specialist modes to existing SSE routes. Add parsing for chunk-split frames, Unicode boundaries, errors, terminal events, and EOF without completion.
- Immediately show the pending user question and stage progress. Keep generated text provisional until validation; only `completed` commits a final answer. Prefer progress-only display initially to avoid showing raw JSON or unvalidated financial claims.
- Add heartbeat/progress during long inference and an AbortController for Stop, mode changes, and unmount. Verify backend disconnect cleanup and capacity release.
- Handle Auto explicitly: either add a bounded unified stream forwarding router/specialist stages, or show an honest non-streaming routing state. Do not claim Auto streaming works from specialist endpoint changes alone.
- Display busy/conflict state and retry guidance without automatic retry storms.

Acceptance: every request reaches completed, failed, or cancelled UI state; no permanent spinner on disconnect or malformed stream; mode switches cannot publish old answers.

### Step 4 — Unify budgets and measure local capacity

Files: `core/config.py`, `agent_harness.py`, `options_agent.py`, `options_model.py`, `unified_chat.py`, `.env.example`.

- Define one configurable overall request deadline with bounded stage allocations and cleanup margin. Provider calls use remaining time; browser timeout exceeds the server deadline by a small explicit margin.
- Measure cold and warm inference before setting defaults. Measure actual model context capacity against prompt plus generation budget; the application's configured estimate is not proof of Ollama's loaded context.
- Add model-specific concurrency admission with a short bounded queue if measurements justify it. Retain the existing one-public-worker and broker-work ownership guarantees.
- Distinguish installed-model health from inference readiness, queue saturation, and measured generation latency. Keep routine health checks lightweight.

Acceptance: artificial slow calls terminate within the documented budget, cancellation does not leak model clients/admission, and concurrent requests have predictable queue or busy responses.

### Step 5 — Verify and release

- Add regression cases for the failures above, including streaming/non-streaming parity, multi-turn/tool output, truncation, disconnect, and busy state across specialists.
- Run repository-required backend and frontend checks after implementation.
- Explicitly run local-model evaluations on sanitized fixtures for all three roles: cold/warm, small/large evidence, follow-ups, invalid data, and concurrent attempts. Mocked tests cannot establish real Qwen output reliability.
- Require every evaluation to produce a validated final answer or a specific bounded error; require no leaked admission slots or unsupported financial assertions. Set a measured valid-answer-rate and latency release target before rollout, and compare against a recorded baseline.
- Deploy only the verified source/build, recording commit, build timestamp, dependency versions, model tag, and effective timeout settings so running code can be distinguished from edited files.

## Checks completed during this diagnosis

`python -m pytest tests/test_options_ollama.py tests/test_portfolio_agent.py -q -p no:cacheprovider`: **39 passed in 31.35 seconds**. These are mocked/offline checks, not evidence that live model answers validate. The empty-list and wrong-UUID validation paths were reproduced independently with synthetic data.

## Documentation checked through Context.dev

- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs
- Ollama concurrency and queue behavior: https://docs.ollama.com/faq
- Ollama native API streaming: https://docs.ollama.com/api/streaming

The application uses OpenAI-compatible SSE, not native Ollama NDJSON; implement the client against the application's SSE contract.


## Implementation update

Core changes implemented in the main checkout: evidence-bound schemas for all three specialists; strict citation rejection; sanitized JSON/schema/citation error codes and run IDs; direct-specialist SSE progress with cancellation; explicit Auto routing state; configurable 110-second server deadline shared by direct/Auto harnesses (90-second Ollama calls remain bounded by remaining overall time).

Automatic model repair, inference-readiness profiling, queue tuning, heartbeat events, and unified Auto streaming remain follow-up work. No live model evaluation or server restart has been performed in this implementation batch. Retain strict failures until real-model evaluations justify a bounded repair strategy.


Verification: frontend 93/93 tests, lint, and production build passed. Backend focused original reply suites 55/55 passed; added regression tests 4/4 passed; follow-up evaluation/MCP/regression group 18/18 passed. Full backend run: 873 passed, 2 skipped, 5 failed; the evaluation mock failure was corrected and its suite passed afterward. Four remaining failures concern HRP unavailable weights (three tests) and unavailable TA-Lib (one test). Dependency consistency check passed; offline options evaluations passed 6/6. These results do not measure live model output quality.


## Completion update

Implemented one repair attempt using the same model instance and cumulative request budgets, with strict validation afterward. Auto mode now has a progress SSE endpoint with five-second status events, cancellation cleanup, and completed-only final answers. The frontend consumes that stream and exposes Stop in Auto mode.

Restarted backend on port 8000; `/api/session` returned HTTP 200. Created local `trading-qwen:16k` from the existing Qwen model with num_ctx=16384 and selected it in the private server environment. Inspection found the original loaded model used only 4096 context tokens despite approximately 8000 estimated input tokens in recorded options runs. The private environment file is not committed.

Live synthetic-evidence smoke tests passed the bound output schema for all three actual specialist factories: chain 22.23s, portfolio 9.83s, risk 22.00s. These are limited live inference checks, not comprehensive financial-quality evaluations or broker-account checks. The broader specialist evaluation was stopped before completion and is not counted as passing. The dedicated risk evaluation CLI declines live mode; risk was checked through its actual factory using synthetic evidence instead.

Latest verification: frontend 93 passed; production build passed; focused backend regression/API group 20 passed. Earlier four unrelated analytics/environment failures remain as documented.
