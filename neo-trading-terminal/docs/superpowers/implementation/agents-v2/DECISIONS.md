# Decisions and documentation

- Integration 2026-11-13: separate default-off tools/advisory/composite rollout flags and bind all three into continuation identity; changing rollout invalidates resumption.
- Source identity uses explicit documented provider neoSymbol and raw master underlying codes/terms/lots. It does not establish cash-token, settlement or exchange-time verification. Withhold expiry-day candidates without authoritative expiry-session metadata.
- Imported IV/RV/basis/correlation/concentration/alpha and conditional ELM/cost/combined stress remain declared scenarios; completeness and production verification are separate acceptance gates. Public next-trade-date ban files require their own validated dated schema; retrieval date is not an effective date.

- User approved extending existing main checkout, advisory proposals, Kotak/public data/imports, staged 30s results.
- Keep options_model.py as LLM provider adapter; calculations use separate quant modules.
- Preserve stronger existing risk/analysis projection boundaries.
- Context7 /agno-agi/docs: output_schema and per-run tool_call_limit supported; application must additionally enforce shared turn budget including prefetch. Source: https://github.com/agno-agi/docs/blob/main/tools/tool-call-limit.mdx
- Context7 FastMCP resolved /prefecthq/fastmcp/v4.1.3 (nearest documented version to pinned 4.1.4); verify installed APIs, do not upgrade automatically.
- Prior source checks found April 2026 STT changes and Tuesday NSE expiry; use dated schedules and contract metadata, never copied timeless rates.
- No HMAC redesign: retain cryptographically random opaque tokens and trusted server records.
- Resume ledger persists in tracked docs rather than disposable scratch to satisfy user continuity requirement.
- Context7 FastMCP 4.1.3 documents on_list_tools/on_call_tool filtering. Retain existing HTTP request middleware and apply explicit role allowlists; do not rely on component visibility alone.
- Fee output remains ESTIMATE until exchange/broker rates and contract-note rounding/aggregation are captured; unknown fee components keep total unavailable.
- Historical-tail kernel accepts validated losses, not raw price histories. Scenario generation and per-series/horizon coverage remain separate work.
- Historical full repricing now uses ordered consecutive source-declared sessions, actual calendar elapsed time and spot/contract-IV relative changes. Portfolio scenarios intersect valid dates across positions; series/horizon tails remain independently available.
- Candidate v1 supports verified bull-call/bear-put debit spreads only; no arbitrary or mixed-underlying leg combination. Additional template types require explicit validation before exposure.
- Context7 /ta-lib/ta-lib-python: function signatures and bundled wheels confirmed. Native TA-Lib 0.6.8 installed, EMA/bandwidth parity checked against NumPy subset.
- Context7 /pyportfolio/pyportfolioopt + installed signature: HRPOpt accepts returns/cov_matrix, not prices. Convert aligned adjusted prices with pct_change(fill_method=None); reject missing/invalid data and exclude noneligible assets.
- Verified dependency compatibility: PyPortfolioOpt 1.5.6 + SciPy 1.16.3. SciPy 1.18.1 removes the library's required private hierarchy API; PyPortfolioOpt 1.6.0 still uses it. Pin 1.16.3 rather than monkeypatching third-party globals. Actual HRP optimization and all 50 focused analytics/MCP cases pass on this set.
- Capture/publication uses the same market -> SQLite lock order as existing chat writes; this avoids inversion/deadlock. Calculations and source IO occur before the publication lock. SQLite waiting is bounded by the remaining capture deadline and precommit validation checks cancellation/session eligibility.
- The opt-in /api/options-agent/analytics/snapshot route is a user evidence refresh, not a model tool. It exposes only role-projected evidence and never captured session-generation values. ANALYTICS_TOOLS_ENABLED defaults false; restart required after enabling it.
- Specialist stages prefetch up to two authorized MCP payloads, counted inclusively, then supply them in user-role JSON to a fresh tool-less specialist. Models have one request and no backup-key retry; numerical output uses evidence paths and is rendered server-side. This prevents an extra model tool call after the two allowed prefetches. Missing-only evidence skips model generation.
- Full composite coordinator and continuation UI are not yet exposed. Stage executor is independently tested using real loopback MCP and a mocked model; no paid/live calls were used.
