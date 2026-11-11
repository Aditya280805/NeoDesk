# NeoDesk agents v2 — approved implementation

Baseline: codex/local-specialist-agents at 57ebe80. Main checkout is the authorized target.

## Global contracts
- Read-only agents; tool-less single-call router; isolated options, analysis and risk evidence.
- Private opaque capabilities bound to owner/role/run/context/session; exact immutable report scopes.
- Eight composite tools; deterministic math, provenance, typed claims and proposals; no invented missing values.
- Candidate proposal IDs embedded in options evidence/pre-bound by server: selecting one costs no third MCP invocation.
- Two MCP invocations per specialist/foreground turn including MCP prefetch; 10s/tool, 30s/turn.
- Explicit continuation, maximum two resumptions, 10-minute expiry, idempotent; invalidate changed session/policy/context/evidence.
- 28-cell full-repricing stress independent from historical VaR/CVaR. >=250 scenarios enables 95%; >=1000 enables 99%; 250–999 leaves only 99% unavailable (insufficient_history_for_99pct).
- Effective-dated rules/fees; Black76 forward conventions, actual expiry ACT365; GEX is a proxy; participant counts are not delta exposure.
- Cash-flow-aware attribution and long-only cash HRP; missing required history stays unavailable.
- Single public worker; additive migrations; backward-compatible existing chat/report APIs; flags default off.

## Dependency/task checklist
- [x] P0: baseline checks; strict versioned routing/evidence/proposal contracts; resume records.
- [ ] P1 (P0): provenance/report adapters, normalized quant inputs, additive history/rule cache.
- [ ] P2 (P0): role-bound discovery/invocation, budget enforcement, sanitation, bounded execution.
- [ ] P3 (P1,P2): technical indicators/regimes and composite tool.
- [ ] P4 (P1,P2): pricing/IV/Greeks/surface and composite tool.
- [ ] P5 (P1,P2,P4): OI/GEX proxy and participant positioning tools.
- [ ] P6 (P1,P2,P4): validated proposals surfaced without extra call; dated fees/payoffs tool.
- [ ] P7 (P1,P2): attribution/HRP tool with coverage.
- [ ] P8 (P1,P2,P6): applicable regulatory checks and post-proposal risk tool.
- [ ] P9 (P4,P8): stress grid and independently available 95%/99% tails.
- [ ] P10 (P3–P9): routing, typed handoffs, deterministic synthesis and continuation.
- [ ] P11 (P10): UI/progress/evidence, flags, CI, docs and full verification.

## Verification
Each behavior: failing focused test then implementation and passing test. Run affected regressions per slice. Final backend pytest, options/platform/specialist evals; frontend test/lint/build; pip check and Docker build where available. Record unavailable verification honestly. No live credential use without explicit authorization.

## Resume protocol
Read STATE.md then DECISIONS.md; inspect git status/diff and relevant recent commits; load only current task files. Preserve user edits. Trust recorded results for unchanged code, rerun affected checks after changes. Update STATE after every verified slice and before handoff. No automatic push/deploy.
