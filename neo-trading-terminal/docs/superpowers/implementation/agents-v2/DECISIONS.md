# Decisions and documentation

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
