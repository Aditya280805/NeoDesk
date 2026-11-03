# NeoDesk — Indian Markets Active Trading & Options Intelligence Terminal

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/next.js-16.4.1-black.svg)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.162.0-009688.svg)](https://fastapi.tiangolo.com/)
[![Broker](https://img.shields.io/badge/broker-Kotak%20Neo%20v3-003366.svg)](https://github.com/Kotak-Neo/kotak-neo-python)
[![MCP](https://img.shields.io/badge/MCP-FastMCP%202.3-purple.svg)](https://modelcontextprotocol.io/)
[![Agent Framework](https://img.shields.io/badge/agent-Agno%20Team-orange.svg)](https://github.com/agno-agi/agno)

A connected Next.js 16 frontend and FastAPI backend multi-user trading platform, featuring an active trader workstation, Kotak Neo broker integration, simulated ₹1,00,000 paper trading accounts, an institutional-grade options engineering suite, and an AI copilot using the Model Context Protocol (MCP) and Agno.

---

## 🏛️ Comprehensive System Design & Architecture

NeoDesk is built with a decoupled client-server architecture engineered for sub-second responsiveness, zero credential leakage, multi-tenant isolation, and mathematically verifiable options analysis.

### End-to-End System Architecture

```mermaid
flowchart TD
    subgraph Client["Frontend Client Layer (Next.js 16.4.1 & React 19)"]
        UI["AppShell & Master Navigation"]
        Ticker["Persistent Multi-Index Ticker Strip\n(Nifty 50, Bank Nifty, FinNifty, Sensex)"]
        Drawer["Global Slide-Over Order Drawer\n(Cross-Route, Body Scroll Lock, Esc Key)"]
        Workstation["Active Trader Workstation (/trading)\n(1-Click Square-Off, Depth, Rapid Actions)"]
        OptionsLab["Options Lab & Scanner (/options, /options-platform)\n(Payoffs, Strike Ladder, Parquet/CSV Backtests)"]
        ChatUI["Options & Portfolio Copilot (/options-chat)\n(Scope Selector, Audit Runs, Verified Badges)"]
        ZStore["Zustand State Store (marketStore.ts)\n(Quotes, Drawer, Ticket Precision)"]
        WSClient["WebSocket Client (services/ws.ts)\n(Auto-Reconnect, User-Scoped Stream)"]
    end

    subgraph Gateway["API Gateway & Security Layer (FastAPI 0.162.0)"]
        AuthMid["JWT Bearer & Cookie Auth Middleware\n(bcrypt Salt, HS256, 24h Expiry)"]
        OriginMid["Origin & CSRF Guard\n(X-NeoDesk: 1 Header, Origin Allowlist)"]
        RateLimit["Adaptive Request & Concurrency Limiter\n(1 Req/User, 4 System-Wide, 6/Min)"]
        MaskMid["Exception Masking Middleware\n(Suppresses MPIN, TOTP, and Secret Echoes)"]
        WSManager["WebSocket Connection Manager\n(app/websocket/manager.py)"]
    end

    subgraph CoreServices["Backend Application Core (Python 3.12)"]
        MarketSvc["Market Quote & Catalogue Service\n(Kotak Neo SDK v3 & Deterministic Sample)"]
        PaperEngine["Paper Trading Engine (app/terminal/paper.py)\n(₹1,00,000 Cash in Integer Paise, FIFO Matching)"]
        RiskManager["Order Risk Manager (app/terminal/risk.py)\n(Single-Order Caps, Daily Loss, Kill Switch)"]
        PortRisk["Portfolio Risk Engine (app/terminal/portfolio_risk.py)\n(Pure Decimal: Concentration, Expiry, Margin, Loss)"]
        OptEngine["Derivatives Analytics Engine\n(NSE OPTSTK Physical Delivery Payoff Modeler)"]
    end

    subgraph BackgroundWorkers["FastAPI Lifespan Background Workers"]
        MatchLoop["Order Match Loop (5s Interval)\n(FIFO Ledger Resolution)"]
        QuoteFeed["Quote Stream Loop (5s Interval)\n(Cached Snapshot Broadcast)"]
        MonitorWorker["Durable Monitor Service\n(OptionsMonitoringService)"]
        ScanWorker["Heavy Scanner Worker\n(OptionsScannerService)"]
        BacktestWorker["Historical Backtest Worker\n(BacktestService)"]
    end

    subgraph AgentLayer["AI Intelligence Layer (Agno & FastMCP 2.3)"]
        TeamRouter["Agno Multi-Agent Router (TeamMode.route)\n(Specialists: Chain vs. Portfolio vs. Clarify)"]
        MCPDaemon["Private FastMCP Daemon (127.0.0.1:8766)\n(ScopeMiddleware Dynamic Tool Fencing)"]
        SpecialistAgent["Options Monitor Agent (@register_agent)\n(Per-Request Factory, 65s Ephemeral Token)"]
        Rotator["KeyRotator 429 Quota Failover\n(Primary Key ➔ Backup Key Auto-Switch)"]
        LLM["Foundation Models\n(Gemini 3.8 Flash / OpenAI GPT-4.1 Mini)"]
    end

    subgraph DataStorage["Data Persistence & Isolation (SQLite WAL)"]
        StoreCore[("Core Database (terminal.sqlite3)\nCompound PKs: user_id + id\nMoney in Integer Paise")]
        StoreTriggers[("Trigger-Enforced Immutability\nBEFORE UPDATE / DELETE ➔ RAISE(ABORT)\n(Artifacts, Reports, Risk Revisions)")]
        KotakAPI["Kotak Neo Broker API v3\n(In-Memory UserMarketSessions, Ephemeral TOTP)"]
    end

    Client -->|HTTP REST / WebSocket| Gateway
    Gateway --> CoreServices
    Gateway --> BackgroundWorkers
    Gateway --> AgentLayer
    CoreServices --> DataStorage
    BackgroundWorkers --> CoreServices
    BackgroundWorkers --> DataStorage
    AgentLayer --> MCPDaemon
    MCPDaemon --> CoreServices
    AgentLayer --> Rotator --> LLM
    MarketSvc <--> KotakAPI
```

---

### Detailed Architectural Subsystems

#### 1. Authentication, Multi-Tenancy & Zero-Storage Broker Security
- **Dual-Token Authentication Pipeline**:
  - User accounts are registered with email, display name, and password. Plaintext passwords are salted and hashed using `bcrypt` (`bcrypt.gensalt()`, `bcrypt.hashpw`).
  - Upon successful authentication, the server generates an HS256 JSON Web Token (`create_token`) with a 24-hour expiration.
  - The token is delivered both as a JSON payload (`access_token`) for the `Authorization: Bearer <token>` header and as an `HttpOnly`, `SameSite=Strict` cookie (`neodesk_token`) for seamless browser navigation.
  - Legacy backward compatibility is preserved via optional `APP_PASSWORD` and `neodesk_session` tokens.
- **Zero-Storage Broker Credentials**:
  - Kotak Neo credentials (`consumer_key`, `ucc`, `mobile`, `totp`, `mpin`) are received over HTTPS via `/api/auth/kotak-login` or `/api/connection/login`.
  - MPIN and TOTP are strictly ephemeral: **they are never written to SQLite, logs, or disk files**.
  - Active broker sessions are maintained exclusively in server RAM as `UserMarketSession` instances inside `Market.user_sessions[user_id]`.
  - When the FastAPI backend restarts, all broker session states instantly vanish from RAM.
  - Multi-tenant broker identity mapping: The `broker_identities` table maps the SHA-256 hash `sha256(f'kotak:{ucc.upper()}'.encode()).hexdigest()` to the tenant's `user_id`, preventing account collisions.
- **Session Generation Fencing**:
  - Each `UserMarketSession` generates a cryptographic UUID token (`generation = str(uuid4())`).
  - Long-running operations and MCP snapshot evaluations execute `assert_generation(user_id, session_generation)`. If the user disconnects or re-authenticates, the session generation changes and running background work is safely aborted.

#### 2. SQLite WAL Storage & Trigger-Enforced Immutability
- **WAL Mode & Busy Handling**:
  - SQLite operates in Write-Ahead Logging mode (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=1000`), allowing non-blocking concurrent reads while background workers execute writes.
- **Compound Primary Key Multi-Tenancy**:
  - Multi-tenant isolation is enforced at the database schema level with compound primary keys and owner checks:
    - `positions (user_id, instrument_id)`
    - `futures_positions (user_id, instrument_id)`
    - `watchlist (user_id, instrument_id)`
    - `orders (user_id, request_id)`
    - `live_requests (user_id, request_id)`
    - `portfolio_risk_policy_revisions (user_id, revision)`
  - All platform store functions validate caller ownership via `_owner(user_id)` assertions (`type(user_id) is int and user_id > 0`).
- **Trigger-Enforced Immutability**:
  - Financial audit trails, strategy artifacts, and risk assessments are cryptographically and database-level immutable. SQLite triggers reject modifications:
    ```sql
    CREATE TRIGGER options_platform_no_update BEFORE UPDATE ON options_platform_artifacts
      BEGIN SELECT RAISE(ABORT, 'immutable platform artifact'); END;
    CREATE TRIGGER options_platform_no_delete BEFORE DELETE ON options_platform_artifacts
      BEGIN SELECT RAISE(ABORT, 'immutable platform artifact'); END;
    CREATE TRIGGER portfolio_risk_reports_immutable BEFORE UPDATE ON portfolio_risk_reports
      BEGIN SELECT RAISE(ABORT, 'immutable risk report'); END;
    CREATE TRIGGER scan_report_no_update BEFORE UPDATE ON platform_scan_reports
      BEGIN SELECT RAISE(ABORT, 'immutable scan report'); END;
    CREATE TRIGGER backtest_report_no_update BEFORE UPDATE ON options_backtest_reports
      BEGIN SELECT RAISE(ABORT, 'immutable backtest report'); END;
    ```
- **Integer Paise Representation**:
  - All fiat money balances (account cash, starting balance, order limit prices, fill prices, position costs) are stored in integer paise (₹1.00 = 100 paise) to eliminate floating-point rounding errors.

#### 3. Market Data Pipeline & Catalogue Matching
- **Dual-Source Market Engine**:
  - Configurable between `sample` (deterministic synthetic market feed for offline simulation and automated tests) and `kotak` (live broker API).
- **Catalogue Scrip Master Ingestion**:
  - Downloads and normalizes over 139,000+ instruments across 4 NSE/BSE market segments: `nse_cm` (NSE Cash), `bse_cm` (BSE Cash), `nse_fo` (NSE Derivatives), and `bse_fo` (BSE Derivatives).
  - Normalizes scrip lot sizes, tick sizes, strike prices (converted from paise), expiry dates, option types (`CE`/`PE`), and contract types (`EQUITY`, `INDEX`, `ETF`, `OPTION`, `FUTURE`).
- **Quote Streaming & WebSocket Architecture**:
  - `Market.quotes(...)` fetches batched quote snapshots (up to 50 instruments per batch) with thread-safe caching (`RLock`).
  - `sfeed_loop` runs every 5 seconds, broadcasting fresh validated quotes over the WebSocket connection manager (`app/websocket/manager.py`) to active user sessions.

#### 4. Paper Trading Engine & Order Execution
- **Double-Entry Cash & Asset Reservation**:
  - When a paper `BUY` limit order is placed, `cash_required = quantity * limit_price` is immediately reserved from the user's available cash balance.
  - When a paper `SELL` limit order is placed, the required quantity is immediately reserved from the user's held position lots, preventing over-selling.
- **FIFO Matching Engine**:
  - `match_loop` runs every 5 seconds in the background. It queries open orders, checks market LTP against limit prices, and executes fills using First-In-First-Out (FIFO) trade accounting.
  - Realized P&L is booked immediately upon matching; unrealized P&L is updated dynamically as market prices change.
- **Live Trading Safety Latch**:
  - Live order routing through Kotak Neo requires **both** `LIVE_TRADING_ENABLED=true` in `.env` and an authenticated broker session.
  - Idempotent request tokens (`request_id` in `live_requests` table) protect against accidental duplicate order submissions.

#### 5. Dual-Layer Risk Management System
- **Layer 1: Interactive Order Risk Manager (`app/terminal/risk.py`)**:
  - Evaluated synchronously before any order (paper or live) is dispatched:
    - `max_order_value`: Caps total order value at ₹5,00,000 (configurable).
    - `max_daily_loss`: Restricts cumulative daily realized loss to ₹25,000.
    - `max_price_deviation_pct`: Blocks limit orders straying > 10% from current LTP.
    - `max_quantity_per_order`: Caps single-order volume at 10,000 units.
    - `kill_switch_active`: Master circuit breaker that halts all order placement immediately when triggered.
- **Layer 2: Portfolio Risk Assessment Engine (`app/terminal/portfolio_risk.py`)**:
  - Pure `Decimal` mathematical evaluation with strict arithmetic contexts (24 digits max, exponent bounds, no IEEE 754 precision loss):
    - `concentration`: Single-underlying portfolio exposure ceiling (`concentration_max_percent`).
    - `expiry`: Warning threshold for contracts expiring within $N$ days (`expiry_window_days`).
    - `margin`: Margin utilization ratio against broker account limits (`margin_max_percent`).
    - `loss`: Maximum allowable unrealized/realized portfolio drawdown (`loss_max_amount`).
  - Observation Freshness Checks: Rejects stale data with `stale_observation` errors if the observation timestamp exceeds the configured freshness window.

#### 6. Derivatives Analytics & Historical Engine
- **Options Payoff Modeler (`options_strategies.py`)**:
  - Evaluates multi-leg options structures (Bull Call Spreads, Bear Put Spreads, Long Straddles, Strangles, Iron Condors).
  - Implements **SEBI / NSE physical delivery settlement rules** for equity derivatives (`nse-optstk-physical-2019.v1`) under SEBI Circulars `SEBI/HO/MRD/DP/CIR/P/2018/144` and `INSP/47293`, distinguishing cash-settled index options from physically delivered stock options.
- **Durable Scanner & Heavy Job Lease Queue (`options_scanner.py`, `options_scan_jobs.py`)**:
  - Scans contracts by Moneyness (ITM/ATM/OTM), IV percentiles, volume surges, and OI concentration.
  - Shared heavy job queue (`platform_heavy` table) manages scanner and backtest leases with concurrency caps (max 20 heavy jobs) and exponential backoff retry handling.
- **Historical Backtesting Engine (`options_backtest.py`, `options_backtest_jobs.py`)**:
  - Offline event replay cursor with matched covered fills and physical ledger tracking.
  - Ingests Parquet and CSV historical datasets (up to 10 MiB) with deterministic SHA-256 content hashing.
  - Models realistic transaction costs, exchange turnover fees, GST, STT, and unitized drawdowns.

---

## 🤖 Implemented AI Agents Architecture

The platform features an enterprise-grade agentic workflow built on the **Model Context Protocol (MCP)** and **Agno**, designed to ensure strict financial correctness, mathematical grounding, and zero unassisted live execution.

### Multi-Agent Interaction & Tool Fencing Sequence

```mermaid
sequenceDiagram
    autonumber
    actor User as Trader
    participant Web as Next.js Web UI (/options-chat)
    participant Limiter as RoutingLimiter (1 Active / 6 Per Min)
    participant Team as Agno Router Team (TeamMode.route)
    participant Specialist as Options Monitor Agent (@register_agent)
    participant FastMCP as Loopback FastMCP Daemon (127.0.0.1:8766)
    participant Core as Backend Core & Broker Engine
    participant Rotator as KeyRotator (429 Quota Failover)
    participant LLM as Google Gemini 3.8 / OpenAI GPT-4.1

    User->>Web: "What is the PCR and strike with highest OI for Nifty?"
    Web->>Limiter: POST /api/options-agent/unified-chat
    Note over Limiter: Verifies concurrency bounds (1 user / 4 system-wide)
    Limiter->>Team: Question + OptionsContext
    Note over Team: 3 Routing Members: Chain vs. Portfolio vs. Clarify (25s Deadline)
    Team->>LLM: Classify intent
    LLM-->>Team: {"scope": "chain"}
    Team-->>Limiter: Scope: chain

    Limiter->>FastMCP: Generate ephemeral Capability (65s lifetime, allowed_tools: [get_option_snapshot])
    FastMCP-->>Specialist: Issue Capability Token (Bearer auth)
    Specialist->>FastMCP: Call tool: get_option_snapshot
    Note over FastMCP: ScopeMiddleware verifies token, checks Origin header, fences tool list
    FastMCP->>Core: Fetch fresh, validated Option Chain snapshot
    Core-->>FastMCP: Immutable Snapshot (LTP, OI, Volume, Strikes, snapshot_id: UUID)
    FastMCP-->>Specialist: JSON Snapshot Payload + snapshot_id

    Specialist->>Rotator: Prompt + Snapshot (grounded context, max 2 tool calls)
    Rotator->>LLM: Inference (Gemini: 4096 tokens, thinking: low / OpenAI: 900 tokens)
    alt Encounter 429 Quota
        LLM-->>Rotator: 429 Quota Limit Exceeded
        Rotator->>LLM: Auto-retry with GEMINI_BACKUP_API_KEY
    end
    LLM-->>Specialist: Pydantic Structured Output: AgentAnswer { answer, snapshot_ids: [UUID] }
    Note over Specialist: Validates snapshot UUID matches retrieved evidence
    Specialist-->>Web: AgentAnswer + audit run record (stored in option_agent_runs)
    Web-->>User: Render grounded answer + verified evidence badges
```

---

### Detailed Agent Inventory & Tool Specifications

| Agent | Scope | Primary Tools | Model & Budget | Core Responsibility |
|---|---|---|---|---|
| **Chat Router Team** | Global | `TeamMode.route` | `gemini-3.8-flash` / `gpt-4.1-mini` | Inspects user query using 3 inline specialists (`chain`, `portfolio`, `clarify`). Routes to appropriate handler within a 25-second deadline. |
| **Options Specialist** | `chain` | `get_option_snapshot` | Max 2 tool calls, 4096 tokens (Gemini) / 900 tokens (OpenAI) | Analyzes option chains, PCR, strike-level OI, and premiums. Enforces explicit disclosures on unverified broker REST freshness. |
| **Portfolio Risk Agent** | `portfolio` | `get_portfolio_snapshot` | Max 2 tool calls, 4096 tokens (Gemini) / 900 tokens (OpenAI) | Evaluates holdings, positions, cash funds, order statuses, and checks portfolio risk policies (`concentration`, `expiry`, `margin`, `loss`). |
| **Strategy Report Explainer** | `strategy` | `get_strategy_report` | Max 2 tool calls, 4096 tokens (Gemini) / 900 tokens (OpenAI) | Explains immutable multi-leg strategy payoff models, physical delivery obligations, breakevens, and margin requirements. |
| **Scanner Report Explainer** | `scan` | `get_scan_report` | Max 2 tool calls, 4096 tokens (Gemini) / 900 tokens (OpenAI) | Explains screener results, candidate rankings, IV filter criteria, and exclusion lists. |
| **Alert Report Explainer** | `alert` | `get_alert_report` | Max 2 tool calls, 4096 tokens (Gemini) / 900 tokens (OpenAI) | Explains durable monitoring alerts, threshold crossings, and state transitions. |
| **Backtest Report Explainer** | `backtest` | `get_backtest_report` | Max 2 tool calls, 4096 tokens (Gemini) / 900 tokens (OpenAI) | Explains historical backtest results, slippage assumptions, fee impact, and unitized drawdown trajectories. |

---

### Agent Security, Guardrails & Harness Controls

1. **Private Loopback FastMCP Server (`127.0.0.1:8766`)**:
   - The MCP daemon runs on a dedicated internal loopback listener via Uvicorn.
   - Non-empty `Origin` headers are immediately rejected with HTTP 401, completely preventing browser-based CSRF attacks or cross-origin exploitation.
   - Capabilities are cryptographically generated server-side using `secrets.token_urlsafe(32)` with a strict 65-second lifetime (`time.monotonic() + 65`).
2. **Dynamic Tool Isolation via `ScopeMiddleware`**:
   - The FastMCP server registers 6 distinct tools: `get_option_snapshot`, `get_portfolio_snapshot`, `get_strategy_report`, `get_scan_report`, `get_alert_report`, and `get_backtest_report`.
   - `ScopeMiddleware` intercepts `on_list_tools` and `on_call_tool`:
     - Dynamically filters tool discovery so the agent only sees the **single tool** authorized for its specific capability scope.
     - Rejects any tool call outside the authorized capability scope with `ToolError('Tool unavailable for this request.')`.
3. **Strict Execution & Token Budgets**:
   - Hard server-side call limit: Maximum 3 total MCP reads per capability (1 prefetch + 2 model calls).
   - Agent tool call limit: `tool_call_limit=2`.
   - Hard generation token limits: 4096 tokens for Google Gemini (`BoundedGemini` with thinking level `'low'`) and 900 tokens for OpenAI (`BoundedOpenAIChat`).
   - Request deadline: 60-second monotonic request deadline.
4. **Deterministic Evidence Verification**:
   - The model cannot answer from parametric memory alone. Output schemas (`AgentAnswer`, `PortfolioAnswer`, `ReportAnswer`) require citing the exact `snapshot_id`, `evidence_id`, or `report_id`.
   - If an agent generates an answer with an incorrect or invented ID, Pydantic validation fails and the response is rejected before reaching the user.
5. **Execution Safety Latch**:
   - Agents are strictly **read-only** (`readOnlyHint: True, destructiveHint: False, openWorldHint: False`).
   - The agent harness possesses zero order placement, fund transfer, or credential modification authority.
   - Any order placement must be explicitly composed by the user on the Trade Ticket and confirmed interactively.
6. **Adaptive Rate Limiting & Concurrency Throttling**:
   - `RoutingLimiter` restricts concurrent chat traffic:
     - 1 active request per user.
     - Maximum 4 concurrent requests system-wide.
     - Maximum 6 requests per minute per user.
7. **Dual-Key Quota Failover (`KeyRotator`)**:
   - Automatic single-retry failover: When a primary API key hits a HTTP 429 quota limit, `KeyRotator` immediately retries the request using `GEMINI_BACKUP_API_KEY` or `OPENAI_BACKUP_API_KEY` without interrupting the user.

---

## ⚡ Active Trader Workstation (`/trading`)

- **Persistent Multi-Index Ticker Strip**: Real-time ticker tracking Nifty 50, Bank Nifty, FinNifty, and Sensex with custom color-coded badges and quote updates.
- **Global Order Drawer**: Slide-over drawer accessible from any page with keyboard shortcuts (`Esc` to dismiss) and body scroll locking.
- **Position Square-Off**: One-click position square-off that automatically calculates the inverse side and quantity and loads it into the trade ticket.
- **Rapid Watchlist & Trade Actions**: Compact row density with instant Buy/Sell quick action buttons.

---

## 🚀 Quickstart

### Launch with PowerShell Script
```powershell
.\run-local.ps1
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. The script compiles the Next.js frontend, packages the static export, and starts the FastAPI server.

To skip rebuilding the frontend if files haven't changed:
```powershell
.\run-local.ps1 -SkipBuild
```

### Manual Setup

#### 1. Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -c requirements.lock
```

#### 2. Frontend
```powershell
cd frontend
npm ci
```

#### 3. Development Servers
- Backend: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` (from `backend/` in `.venv`)
- Frontend: `npm run dev` (from `frontend/`, opens at `http://localhost:3000`)

---

## ⚙️ Configuration (`.env`)

Copy `.env.example` to `.env` in `neo-trading-terminal/`:

```ini
ENVIRONMENT=development
PAPER_STARTING_BALANCE=100000
TRADING_MODE=paper
LIVE_TRADING_ENABLED=false
MARKET_DATA_SOURCE=sample

# Kotak Neo Broker Credentials (or enter via UI at /login)
KOTAK_CONSUMER_KEY=
KOTAK_UCC=
KOTAK_MOBILE_NUMBER=
KOTAK_ENVIRONMENT=prod

# AI Options Assistant
GEMINI_API_KEY=
GEMINI_BACKUP_API_KEY=
OPENAI_API_KEY=
OPTIONS_AGENT_PROVIDER=gemini
OPTIONS_AGENT_MODEL=gemini-3.8-flash
OPTIONS_AGENT_ENABLED=true
OPTIONS_MCP_PORT=8766
```

---

## 🧪 Testing & Empirical Verification

```powershell
# Run backend tests (560+ test cases)
cd backend
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest tests -q

# Run offline agent eval replay
.\.venv\Scripts\python.exe -m app.terminal.options_evals
.\.venv\Scripts\python.exe -m app.terminal.options_evals --scope portfolio
.\.venv\Scripts\python.exe -m app.terminal.options_evals --scope portfolio-risk
.\.venv\Scripts\python.exe -m app.terminal.options_platform_evals

# Run frontend tests (67 test suites)
cd ..\frontend
npm test

# Run frontend linter & production build
npm run lint
npm run build
```

---

## 📜 Technical Guides & Deep-Dives

- [Options Agent & MCP Harness Architecture Guide](docs/OPTIONS_AGENT.md)
- [Options Workspace & Data Platform Specifications](docs/OPTIONS_PLATFORM.md)
- [Kotak SDK & Market Data Documentation](docs/DATA_AND_TRADINGVIEW.md)
- [Render Cloud Deployment Guide](docs/DEPLOY_RENDER.md)

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](../LICENSE) file for details.
