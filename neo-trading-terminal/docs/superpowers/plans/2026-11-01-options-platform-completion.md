# Complete Options Platform Implementation Plan

> Required execution: superpowers:subagent-driven-development, fresh implementer/task reviewer, sequential tasks.

**Goal:** Complete the approved read-only options platform with usable UI/API/MCP interfaces and honest unavailable/live statuses.
**Spec:** docs/superpowers/specs/2026-11-01-options-platform-completion.md (user approved).
**Architecture:** Existing single-worker FastAPI/SQLite/Agno/private MCP; pure calculation modules and durable worker jobs. Current dirty feature checkout contains required untracked foundation; no commits/reset/staging/push/deploy.

## Global constraints
- Preserve Phase0–2, manual-trading modules and unrelated UI work. All new endpoints require explicit authenticated user, never fallback user1.
- Model remains read-only. Browser state changes are authenticated; reports are immutable and owner scoped.
- Decimal strings/null and original evidence times; never invent broker capabilities or current rules.
- Preserve existing request budgets, retained cancelled-worker capacity and generation fences; .venv-harness interpreter.
- No paid purchases/live credential disclosure. Opt-in smoke and model experiments only; no live calls automatically during tests.
- One active monitor/user, 60-second default, one heavy job globally, bounded queue 20 and page size50/max100.
- Fresh reviews use before/after file snapshots because commits prohibited. Keep ledger and artifacts.

## Tasks
1. Data readiness and canonical strategy market contracts: source inventory, validated optional fields and capability gating, explicit smoke CLI. New options_market_contracts.py/options_readiness.py and focused tests; compatibility with existing snapshots.
2. Strategy engine and persistence/API: covered calls/collars, owned/hypothetical, costs/executable quotes/eligibility/capital/payoffs, immutable baselines and owner-scoped service. New options_strategies.py/options_platform_store.py/routers/options_platform.py and tests. Use Task1 typed evidence; no trading integration.
3. Risk and monitoring: expanded policy/history/association calculations, durable jobs/alerts/shared capacity/lifespan, owner API and restart/session/cancel tests. Reuse Task2 baselines/store and portfolio service. All financial thresholds unset.
4. Scanner: typed user criteria, versioned universe, durable resumable jobs, deterministic filters/rankings/exclusions with capacity sharing. Use Task1/2 contracts and Task3 jobs; focused tests including partial/cancel/quota/restart.
5. Backtesting/import: validated bounded CSV/Parquet ingestion, point-in-time engine using Task2 calculations, corporate-action/settlement/gap handling, owner jobs/results. Synthetic reference fixtures and tests for lookahead/fills/equity/costs.
6. MCP/chat: scoped report readers for strategy/scan/alert/backtest through existing private server and Agno runner, auth/discovery/read tests, exact evidence/citations and bounded context. No model write tools.
7. Frontend: coherent options workspace for analyses/baselines, criteria/scans, monitor settings/alert inbox, data imports/backtest results and explanations. Reuse existing authentication/navigation/styles, preserve other work. Tests/build/lint + controlled browser flows.
8. Evaluation/research/release: offline benchmark all capabilities, opt-in model comparison runner and held-out human rubric, fine-tuning and data-source assessment with explicit unmet live status, docs, full backend/frontend/offline gates and broad final review.

Each task: write meaningful failing tests, run RED, implement, run GREEN, snapshot diff and independently review; fix important findings before next dependency. Detailed briefs contain stable cross-task interfaces and rulings.

## Review focus
Partial contract/quote semantics must not become eligibility; owned versus hypothetical capital and fees must be explicit; background work must retain cancellation capacity; job restart/cross-user selection must not mutate another account; incomplete/point-in-time history must not fabricate performance. All are hard acceptance tests in owning tasks.
