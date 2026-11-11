# Execution state

- Baseline: 57ebe80, codex/local-specialist-agents, clean before this run.
- Active: P1/P2 foundations; P4/P5/P6/P8/P9 calculation kernels introduced, not complete packages.
- Completed: P0 baseline (40 passing specialist/router regressions), strict versioned routing/evidence/proposal contracts, durable records.
- Implemented: immutable owner-bound evidence SQLite store; shared per-role two-call budget; cancellation-safe capacity; optional role-scoped eight-tool MCP registration; Black76/IV and Greek kernels; independent historical loss tails and 28-cell stress; participant CSV parser; dated STT/stamp arithmetic; returned-chain OI; conservative compliance skeleton.
- Next: full tool payload calculation and validated source acquisition; technical/surface/attribution; continuation/orchestration/UI. Existing tools remain default; analytics connection opt-in only.
- Tests: test_analytics_v2.py 16 passed after fixture correction. Earlier combined MCP regression run: 29 passed, one test-only Mock fixture failure now corrected; rerun combined suite after next MCP edits. Baseline 40 passed. Use -p no:cacheprovider (old .pytest_cache permissions deny writes).
- Limitations: no live analytics request path yet; regulatory checks beyond lots/ban remain cannot_assess; GEX/surface/HRP and live sources pending. Do not claim P1–P11 complete.
- Ownership: all changes under this implementation are agent-owned; initial checkout had no uncommitted edits.
- Resume: read PLAN.md and DECISIONS.md, inspect diff; continue first unchecked package. Never mark a package complete for scaffolding alone.
