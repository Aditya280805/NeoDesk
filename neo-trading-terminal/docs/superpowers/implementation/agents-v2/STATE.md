# Execution state

## Resume here — 2026-11-13 verified integration (authoritative)

Workspace: `C:/Users/Aditya Bose/OneDrive/Documents/TRADING`, branch `codex/local-specialist-agents`; do not use the detached d51e worktree. Previous checkpoint `5e648f3`; identify this verified integration by the next commit, `feat(analytics): integrate validated sources, proposals and rollout controls`.

Implemented in this integration:
- Raw documented master metadata cross-checks with provider `neoSymbol`, underlying code, contract terms and per-contract lot. Fresh bounded bid/ask depth produces server candidates in exactly one existing options payload. Expiry-day candidates are withheld; no guessed settlement time. Broker-code identity does not verify cash token, settlement or exchange timestamp.
- Exact gross spread payoff; entry statutory components; optional strictly contract/quantity/quote/time-bound declared fixed cost scenario. Missing broker/exchange/closing/exercise costs keep complete net payoff unknown. Safe browser paise bounds enforced.
- Owner-private immutable imported dataset references survive continuation. Matched position/surface inputs support combined supplied-position 28-cell stress and independent historical tails; complete-account coverage remains false. Account-derived risk reports are risk-only; fast account-source failure preserves other evidence and cannot bypass session/policy/deadline checks.
- Strict single-batch broker daily OHLCV adapter, previous OI/price normalization, six-session declared participant changes/divergence and institutional-retail heuristic; official/imported participant revisions stay distinct.
- Effective-dated expiry ELM/calendar applicability, conditional declared additional ELM amount and aggregate FutEq limit scenarios. These do not compute complete SPAN/broker margin or certify account compliance.
- Mounted dated IV history/RV inputs; cash-return correlation matrices, asset/sector HHI and annualized benchmark regression alpha. Intraday VIX observations cannot substitute for daily VIX history.
- Separate default-off `ANALYTICS_TOOLS_ENABLED`, `ANALYTICS_ADVISORY_ENABLED`, `ANALYTICS_COMPOSITE_ENABLED`. Composite UI requires both tools and composite switches. Proposals require advisory switch.
- UI session-expiry fencing, readable evidence/missing reasons, responsive desktop/mobile layout; isolated synthetic browser fixture and screenshots; 20-case router contract replay added to Linux/Windows CI. Replay is explicitly not model-quality evaluation.

Final frozen-code verification: full backend working-tree suite **775 passed in 318.38s**; frontend **92 passed**, lint and production build passed; isolated Chrome desktop/mobile checks passed (proposal display, evidence, continuation binding, zero page errors, no mobile horizontal overflow). Options/platform/specialist/analytics offline eval modules all exited 0; router contract replay 20/20 explicitly does not measure model quality. pip check passed; staged options-agent syntax and staged diff whitespace checks passed. Earlier timing-sensitive portfolio test failure under concurrent runs passed the focused rerun and final full suite; no concurrent provider test was changed. Docker CLI is unavailable, remote CI not run, no live broker/model calls.

Next work: obtain explicit read-only live broker/model validation authorization and representative sanitized dated source inputs, then complete the source-backed adapters/calculations named in COMPLETION-GAPS.md (automatic adjusted portfolio/IV/trade histories, complete fees, dated ban/MWPL and complete-account margin/limits, sector performance). Public NSE ban CSV probe timed out; do not invent its effective date/schema. Existing scenario paths remain usable with explicit missing coverage. No push/deploy or execution authorization. Preserve provider-owned .env.example, agent_harness/options_model/specialist_agents/server/router changes and their tests; only analytics constructor/status hunks from options_agent.py belong to this integration.

Review found VIX daily-basis error (RED then GREEN); earlier non-ISO expiry and unsafe paise findings were also fixed with regressions. Remaining source/adapter gaps are listed in COMPLETION-GAPS.md. P0–P11 must not be declared fully complete based on offline tests.

Read only this section and COMPLETION-GAPS.md when resuming, inspect git status/log, then load affected files. Older detailed history can be recovered from git; do not repeat completed slices.
