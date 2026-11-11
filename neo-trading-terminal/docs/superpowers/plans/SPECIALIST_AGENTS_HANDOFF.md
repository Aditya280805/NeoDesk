# Specialist Agents Part 1 Handoff Document

This document serves as the official specification and verification record delivered by Part 1 (Heavy Core Implementation) for consumption by Part 2 (Basic Integration).

---

## 1. Explicit Warning & Start Condition for Part 2

> [!CAUTION]
> **Part 2 MUST NOT run on a pre-Part-1 codebase (`main` at `a54d9e1`).**
> Any attempt to execute Part 2 without the completed Part 1 commit chain will result in missing specialist endpoints, missing isolated MCP projections, broken contracts, and build failures.
>
> Before editing any files in Part 2, verify:
> 1. Presence of this handoff: `docs/superpowers/plans/SPECIALIST_AGENTS_HANDOFF.md`
> 2. Presence of all 5 frozen fixtures: `backend/evals/fixtures/specialist_api/{chain,portfolio,risk,clarify,scope_change}.json`
> 3. Total absence of `options_monitor` and `build_agent` in active runtime/evaluation code.
> 4. Clean git status on `codex/local-specialist-agents` with `HEAD` at or after commit `c20aaf5`.

### Required Pre-flight Verification Commands

Run these commands from repository root before starting Part 2:

```powershell
git status --short
git log -1 --oneline
Test-Path docs/superpowers/plans/SPECIALIST_AGENTS_HANDOFF.md
Get-ChildItem backend/evals/fixtures/specialist_api
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_specialist_evals.py -q -p no:cacheprovider
```

---

## 2. Prerequisite Branch & Verified Commit History

All heavy core architecture, isolated specialist agents, MCP tool projections, request harnesses, and evaluation suites are completed on branch `codex/local-specialist-agents`.

### Verified Commit History Chain

1. `18484d2` feat(specialist-agents): commit verified H1-H3 baseline before Tasks 7-10
2. `a22de10` feat(options-agent): migrate explicit specialist APIs and retire catch-all callers (Task 7)
3. `d8d9362` feat(options-agent): implement tool-less master router and sticky follow-ups (Task 8)
4. `428f1d8` fix(options-agent): persist parent run across all failure branches and test citation guard (Task 8 fix)
5. `96d238a` feat(evals): add offline specialist evaluation suite and retire options_monitor (Task 9)
6. `cb8471a` fix(evals): implement live-model execution, routing accuracy, and call metrics (Task 9 fix)
7. `53df1cd` feat(evals): generate frozen specialist API fixtures and Part 2 handoff (Task 10)
8. `c20aaf5` fix(unified-chat): fail closed with 404 when history is None and clean specialist evals (Code fix review)

Part 2 must start from branch `codex/local-specialist-agents` at `HEAD` (at or after `c20aaf5`).

---

## 3. Specialist & Router Architecture Map

Specialist agents are registered in `AGENT_REGISTRY` (`app/terminal/agent_registry.py`) and constructed per request using fresh factories (`app/terminal/specialist_agents.py` and `app/terminal/unified_chat.py`). No persistent agent instances or shared conversation histories cross specialist boundaries.

| Agent Name | Agent ID | Scope | Prompt Version | Allowed Tool | Output Schema | Injected Context & Evidence |
|---|---|---|---|---|---|---|
| Options Specialist | `options_trading_analysis` | `chain` | `chain.1` | `get_option_snapshot` | `AgentAnswer` (`answer`, `snapshot_ids: [str]`) | `OptionsContext` (`underlying`, `exchange`, `expiry`), `OptionSnapshot` |
| Portfolio Analysis Specialist | `portfolio_analysis` | `portfolio` | `analysis.1` | `get_portfolio_analysis_snapshot` | `PortfolioAnalysisAnswer` (`answer`, `evidence_ids: [UUID]`) | `PortfolioSnapshot` (holdings, positions, funds, orders, data quality; **strictly no risk fields**) |
| Portfolio Risk Specialist | `portfolio_risk` | `risk` | `risk.1` | `get_portfolio_risk_report` | `PortfolioRiskAnswer` (`answer`, `evidence_ids: [UUID]`, `risk_report_ids: [UUID]`) | `evidence_id` + deterministic `RiskReport` (**strictly no holdings/positions/funds rows**) |
| Master Router | `master_router` | `clarify` (or routes to `chain`, `portfolio`, `risk`) | `master_router.1` | None (Tool-less Agno Team) | `RouteAnswer` (`scope: Literal['chain','portfolio','risk','clarify']`) | Untrusted message + at most 4 previous turn messages; no private tools or evidence |
| Saved Report Specialist | `options_trading_analysis` | `strategy`, `scan`, `alert`, `backtest` | `saved-report.1` | `get_{kind}_report` | `ReportAnswer` (`answer`, `report_ids: [str]`, `evidence_ids: [str]`) | Immutable saved report artifact |

---

## 4. Endpoints, Request/Response Fields & HTTP Error Behavior

### 4.1 Specialist Chat Endpoints

#### `POST /api/options-agent/chat`
- **Purpose**: Explicit option chain analysis.
- **Request Body** (`ChatRequest`):
  ```json
  {
    "underlying": "NIFTY",
    "exchange": "nse_fo",
    "expiry": "26Nov2026",
    "message": "Analyze ATM strikes, volume, and open interest for NIFTY.",
    "conversation_id": null
  }
  ```
- **Response Body** (`200 OK`):
  ```json
  {
    "conversation_id": "2729dccc-f050-4093-b776-d22d04f3a89e",
    "run_id": "7ea465d4-6816-4c5d-bed4-4c913212e0d3",
    "parent_run_id": "7ea465d4-6816-4c5d-bed4-4c913212e0d3",
    "agent_id": "options_trading_analysis",
    "answer": "ATM strike 24000 call premium is 110.00...",
    "created_at": "2026-11-11T10:32:49.433856+00:00",
    "read_only": true,
    "snapshot_ids": ["c26a004a-dd2d-4df1-9863-cb391641f6a9"],
    "snapshot": { ... }
  }
  ```

#### `POST /api/options-agent/portfolio/chat`
- **Purpose**: Explicit portfolio balances, holdings, positions, and orders analysis.
- **Request Body** (`PortfolioChatRequest`):
  ```json
  {
    "message": "Summarize portfolio cash balances, holdings, and open positions.",
    "conversation_id": null
  }
  ```
- **Response Body** (`200 OK`):
  ```json
  {
    "conversation_id": "792706a2-f661-4675-a657-f8ae1291399e",
    "run_id": "c989ca12-1be2-4e5c-9ae3-2d0ec1da2a8e",
    "parent_run_id": "c989ca12-1be2-4e5c-9ae3-2d0ec1da2a8e",
    "agent_id": "portfolio_analysis",
    "answer": "Portfolio funds show 100000.00 available cash balance...",
    "created_at": "2026-11-11T10:32:49.522263+00:00",
    "read_only": true,
    "evidence_ids": ["c3f91bd5-2058-4ba7-a3fd-ceddfac89e4f"],
    "portfolio_snapshot": { ... }
  }
  ```
  *(Note: `risk_report`, `risk_inputs`, and `risk_report_ids` are strictly omitted)*.

#### `POST /api/options-agent/portfolio/risk/chat`
- **Purpose**: Explicit portfolio risk evaluation (concentration, expiry, margin, loss limits).
- **Request Body** (`PortfolioChatRequest`):
  ```json
  {
    "message": "Check portfolio risk limits, margin headroom, and concentration rules.",
    "conversation_id": null
  }
  ```
- **Response Body** (`200 OK`):
  ```json
  {
    "conversation_id": "36d653d7-37e5-442a-8e9d-03d794e9e7e8",
    "run_id": "cfdf4613-e1cc-4f70-b705-54d5c3a78773",
    "parent_run_id": "cfdf4613-e1cc-4f70-b705-54d5c3a78773",
    "agent_id": "portfolio_risk",
    "answer": "Portfolio risk checks pass: concentration...",
    "created_at": "2026-11-11T10:32:49.583579+00:00",
    "read_only": true,
    "evidence_ids": ["475d2c75-db94-4b4e-bcc4-73d9471edc32"],
    "risk_report_ids": ["df0940cf-2721-474b-ba15-abfaec4731f6"],
    "risk_snapshot": {
      "evidence_id": "475d2c75-db94-4b4e-bcc4-73d9471edc32",
      "risk_report": { ... }
    }
  }
  ```
  *(Note: Contains only `evidence_id` and `risk_report`. Holdings/positions/funds/orders tables are strictly absent)*.

#### `POST /api/options-agent/unified-chat`
- **Purpose**: Auto-select routing between chain, portfolio, risk, and clarify.
- **Request Body** (`UnifiedChatRequest`):
  ```json
  {
    "message": "User query here",
    "conversation_id": null,
    "context": {
      "underlying": "NIFTY",
      "exchange": "nse_fo",
      "expiry": "26Nov2026"
    },
    "report_kind": null,
    "report_id": null
  }
  ```
- **Clarification Response Body** (`200 OK`):
  ```json
  {
    "scope": "clarify",
    "agent_id": "master_router",
    "run_id": "62796905-7b10-4897-8788-5d17e31ec806",
    "parent_run_id": "62796905-7b10-4897-8788-5d17e31ec806",
    "conversation_id": null,
    "answer": "Please ask separately about an option chain, portfolio analysis, or portfolio risk.",
    "read_only": true
  }
  ```
- **Routed Response Body** (`200 OK`): Returns `scope: "chain" | "portfolio" | "risk"` merged with the corresponding specialist reply envelope (including `parent_run_id`).

#### `POST /api/options-platform/explain`
- **Purpose**: Saved report analysis (`strategy`, `scan`, `alert`, `backtest`).
- **Request Body** (`ReportChatRequest`):
  ```json
  {
    "message": "Explain this backtest result.",
    "report_kind": "backtest",
    "report_id": "550e8400-e29b-41d4-a716-446655440000",
    "conversation_id": null
  }
  ```

#### Non-Agent Snapshot & History Endpoints
- `POST /api/options-agent/portfolio/snapshot`: Fast non-agent UI refresh returning `PortfolioRiskEnvelope` (raw portfolio snapshot + deterministic risk report).
- `GET /api/options-agent/conversations/{conversation_id}`: Hydrates conversation history. Returns `snapshot`, `portfolio_snapshot`, `risk_snapshot`, or `report` depending on stored context scope, with backward-compatibility for legacy `portfolio.v1` turns.
- `GET /api/options-agent/runs/{run_id}`: Retrieves sanitized run execution audit record, including parent/child IDs, stage timing, and `harness` token/call traces.

---

### 4.2 HTTP Status & Error Codes

| Status Code | Reason / Condition | Response Body |
|---|---|---|
| `200` | Successful execution | Specialist or router envelope |
| `401` | Unauthenticated | `{"detail": "Sign in to your individual account to use options monitoring."}` |
| `403` | Origin or CSRF header missing | `{"detail": "Request origin rejected."}` |
| `404` | Conversation or run record not found | `{"detail": "Conversation not found."}` or `{"detail": "Run not found."}` |
| `409` | **Conversation Scope Changed** | `{"detail": {"code": "conversation_scope_changed", "message": "Start a new conversation after changing scope, specialist, or market selection."}}` |
| `409` | Concurrency guard | `{"detail": "An options request is already running. Please wait."}` |
| `422` | Request validation failure | `{"detail": "Invalid request fields. Check the values and try again."}` |
| `429` | Rate limit exceeded | `{"detail": "Options chat is busy. Please wait a minute before retrying."}` or routing limiter |
| `503` | Provider/MCP/Storage error | Safe message; prompts/secrets never leaked in error response |
| `504` | Execution timeout (60s/85s) | `{"detail": "Options chat timed out. Retry after the current request finishes."}` |

---

### 4.3 CRITICAL Part 2 Frontend Integration Warning: Object `detail` Handling

> [!WARNING]
> **Issue in `frontend/src/lib/api.ts`:**
> `frontend/src/lib/api.ts` currently extracts error messages via:
> ```typescript
> throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`)
> ```
> When the backend returns a 409 scope change error, `data.detail` is a structured JSON object:
> ```json
> {
>   "detail": {
>     "code": "conversation_scope_changed",
>     "message": "Start a new conversation after changing scope, specialist, or market selection."
>   }
> }
> ```
> Because `typeof data.detail === 'object'`, `api.ts` will discard the message and throw `Request failed (409)` unless updated!
>
> **Part 2 Action Required:**
> In Part 2 Task 1 & Task 2, update `frontend/src/lib/api.ts` error handling (or handle response in `options-chat.tsx`) so structured `data.detail` objects are recognized:
> ```typescript
> const message = typeof data.detail === 'string' 
>   ? data.detail 
>   : (data.detail?.message || `Request failed (${response.status})`);
> ```
> And expose `data.detail?.code === 'conversation_scope_changed'` so the UI can preserve user drafts and prompt for a new chat rather than failing silently.

---

## 5. Sanitized Frozen Fixture Locations & Envelope Schema

All five fixtures are programmatically generated and frozen under `backend/evals/fixtures/specialist_api/`:

| Fixture File | Scope | Status | Agent ID | Endpoint Path |
|---|---|---|---|---|
| `backend/evals/fixtures/specialist_api/chain.json` | `chain` | 200 | `options_trading_analysis` | `/api/options-agent/chat` |
| `backend/evals/fixtures/specialist_api/portfolio.json` | `portfolio` | 200 | `portfolio_analysis` | `/api/options-agent/portfolio/chat` |
| `backend/evals/fixtures/specialist_api/risk.json` | `risk` | 200 | `portfolio_risk` | `/api/options-agent/portfolio/risk/chat` |
| `backend/evals/fixtures/specialist_api/clarify.json` | `clarify` | 200 | `master_router` | `/api/options-agent/unified-chat` |
| `backend/evals/fixtures/specialist_api/scope_change.json` | `scope_change` | 409 | `null` | `/api/options-agent/unified-chat` |

### Uniform Envelope Schema

Every fixture JSON file strictly conforms to:
```typescript
interface SpecialistApiFixture {
  endpoint: string;       // Exact endpoint path
  method: "POST";         // HTTP Method
  status_code: 200 | 409; // Observed HTTP status code
  scope: "chain" | "portfolio" | "risk" | "clarify" | "scope_change";
  agent_id: "options_trading_analysis" | "portfolio_analysis" | "portfolio_risk" | "master_router" | null;
  request: Record<string, unknown>;   // Valid request body matching Pydantic request models
  response: Record<string, unknown>;  // Verbatim response returned by FastAPI endpoint
}
```

---

## 6. Verbatim Observed Verification Results

All tests, evaluators, and checks have been empirically executed and verified in Task 10:

### 1. `pip check`
```text
WARNING: Ignoring invalid distribution ~tarlette (...)
No broken requirements found.
```
*(Returncode: 0)*

### 2. Specialist Evals Test Suite (`pytest tests/test_specialist_evals.py`)
```text
.........                                                                [100%]
9 passed in 23.50s
```
*(Tests verified: offline contract, cases/rubric file integrity, offline CLI, live-model opt-in, live-model mock execution, absence of options_monitor/build_agent, frozen fixture existence and envelope schema, frozen fixture contract validation and cross-scope isolation, secret sentinel scan)*.

### 3. Specialist Evals Offline CLI (`python -m app.terminal.specialist_evals --mode offline`)
```text
Total samples: 18, Passed: 18, Failed: 0
By split:
  development: 9 passed / 9 total
  held_out:    9 passed / 9 total
By scope:
  chain:       7 passed / 7 total
  portfolio:   5 passed / 5 total
  risk:        4 passed / 4 total
  clarify:     2 passed / 2 total
Category summaries:
  routing:     3 passed / 3 total
  numeric:     9 passed / 9 total
  citation:    13 passed / 13 total
  abstention:  18 passed / 18 total
```
*(Returncode: 0)*

### 4. Options Evals Scope CLIs (`python -m app.terminal.options_evals --scope ...`)
- `python -m app.terminal.options_evals --scope chain`:
  ```text
  Mode: offline, Scope: chain, Total: 6, Passed: 6
  ```
- `python -m app.terminal.options_evals --scope portfolio`:
  ```text
  Mode: offline, Scope: portfolio, Total: 11, Passed: 11
  ```
- `python -m app.terminal.options_evals --scope portfolio-risk`:
  ```text
  Mode: offline, Scope: portfolio-risk, Total: 11, Passed: 11
  ```
*(All returncodes: 0)*

### 5. Catch-All Caller & Dead Agent Grep Check
- `git grep "options_monitor" -- neo-trading-terminal/backend`: Confirmed 0 active agent references (only `assert 'options_monitor' not in list_agents()` in tests).
- `git grep "build_agent" -- neo-trading-terminal/backend`: Confirmed 0 active factory references (only negative assertions in tests).

### 6. Fixture JSON Parse & Secret Sentinel Scan
- All 5 fixtures confirmed 100% valid JSON.
- Automated scan across all 5 fixture files and `SPECIALIST_AGENTS_HANDOFF.md` confirmed zero presence of authorization bearer tokens, secret sentinels, session generation identifiers, capability tokens, test keys, API key patterns, or real tokens/secrets.

---

## 7. Explicitly Deferred Work (Do Not Claim Complete)

The following areas are explicitly reserved for future work and MUST NOT be claimed as complete by Part 1 or Part 2:
1. **Live Ollama / Gemini Quality Benchmarking**: Offline replay verifies contract conformity and routing accuracy; live LLM prose quality, phrasing nuance, and hardware-specific benchmark scores remain unmeasured.
2. **Ollama Local Weights & Model Availability**: Ollama provider loopback transport is wired and tested, but local model downloading and GPU memory management are environment-dependent.
3. **Memory & Strategy Agents**: Long-term persistent vector memory, cross-session user profiling, and autonomous strategy proposal agents are intentionally out of scope.
4. **Order Execution & Broker Actions**: All specialist agents and routers are strictly read-only; trade order placement, position modifications, and funds transfers remain disabled by design.
5. **Multi-Agent Autonomous Collaboration**: The master router performs strict classification and dispatching; unconstrained peer-to-peer agent deliberation without human routing is omitted.
6. **Part 2 Frontend Integration**: UI specialist selector buttons, Auto-mode badge, draft preservation upon 409 scope change, and documentation updates (`docs/OPTIONS_AGENT.md`) are the explicit responsibility of Part 2.
