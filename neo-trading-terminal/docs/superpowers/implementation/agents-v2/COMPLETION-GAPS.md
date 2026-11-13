# Acceptance and release gates — 2026-11-13

P0–P11 are not fully accepted. Offline tests establish the behavior below; they do not establish live data availability or model quality. No percentage estimate substitutes for this matrix.

| Phase | Implemented and exercised locally | Remaining acceptance evidence/work |
| --- | --- | --- |
| P0 | Strict versioned contracts; durable resume records | None for foundation slice |
| P1 | Owner-bound immutable inputs, additive cache, chain/depth/master identity, broker daily history, typed imports | Automatic authenticated adjusted asset/benchmark/IV histories, fills/cash-flow mappings and verified rule/fee/margin input adapters remain incomplete |
| P2 | Role capabilities, isolation, two-read budgets including prefetch, deadlines, retained cancellation capacity, sanitation; real local model/MCP smoke with synthetic sources | Broader authenticated runtime/source coverage |
| P3 | TA-Lib indicators/regimes, session VWAP, daily-basis VIX guard, bounded history/import path; up to three nonoverlapping daily batches to warm EMA200 under the shared deadline | Actual historical/VIX coverage and live validation of the extended history path |
| P4 | Black76/IV/Greeks, expiry-specific forward/rate inputs, surfaces, mounted dated IV history/RV | Automatic authoritative pricing/IV-history/actual-expiry sourcing and live fixtures |
| P5 | OI/PCR/walls/pain/buildup with provided previous OI/price, GEX proxy, declared synchronized cash/future basis, participant acquisition/history | Automatic prior-OI/cash-futures basis/complete participant-session and cash-flow histories |
| P6 | Server candidates inside existing payloads; no third MCP call; gross payoff, statutory fees, bound conditional costs | Complete dated broker/exchange/closing/exercise schedules, contract-note reconciliation, settlement/exchange timestamp proof |
| P7 | Ratios, beta/alpha, cash HRP/correlations/HHI, declared trades, sector allocation and daily-weighted cash-sleeve sector performance | Authenticated adjusted cash/trade/cash-flow adapters and verified complete performance data remain incomplete |
| P8 | Risk-only derived account report, dated lot/ban/FutEq scenarios, ELM/calendar applicability and conditional ELM increment, supplied-position post-proposal stress | Official dated ban/MWPL acquisition, verified account-wide/intraday FutEq/limits, complete calendar/SPAN/broker margin and complete-account aggregation remain incomplete |
| P9 | 28-cell repricing; per-series/per-horizon tails; independent 95% >=250 and 99% >=1000 availability | Verified representative production history/input coverage |
| P10 | Single-label classifier with server-bound roles, ordered stages, typed handoff, server-bound numerical/proposal references, continuation; local live canonical20/20 and initial heldout9/10 with missed case subsequently fixed | Broader independent model/question coverage; see LIVE-VALIDATION.md for the distinction between initial heldout and regression retest |
| P11 | Responsive opt-in UI, evidence/missing inputs, session fences, independent default-off flags, CI definitions, docs, synthetic browser checks | Remote CI, Docker on available host, live smoke validation and release approval |

Internal work is distinct from external validation: adapters/calculations explicitly named above remain implementation work. Missing-data behavior and declared scenarios are not verified production coverage.

Source probe update: bounded HTTPS acquisition succeeded on2026-11-13. The official CSV explicitly states its trade date in the first line and supplies numbered symbol rows. A strict date-bound parser is implemented and locally tested; mounting acquisition/cache into capture and validating empty-day formats remain incomplete. Never infer the trade date from download time.

Read-only live-check authorization was granted by the user's continuation after the explicit request. Local model checks have run. The user subsequently signed in: the live UI confirms broker connectivity, populated holdings/funds and159,551 indexed instruments, while positions/orders fail and holdings identity matching remains pending. Further integration needs diagnosis of those responses, representative sanitized fixtures and authoritative dated schedules. Authorization does not cover orders, execution or deployment.

Default rollout: ANALYTICS_TOOLS_ENABLED=false, ANALYTICS_ADVISORY_ENABLED=false, ANALYTICS_COMPOSITE_ENABLED=false. Tools enable snapshots; advisory additionally enables eligible hypothetical candidates; composite additionally enables unified analytics chat/UI.

Official references: [NCL expiry ELM](https://nsearchives.nseindia.com/content/circulars/CMPT64639.pdf), [index calendar rule](https://nsearchives.nseindia.com/content/circulars/CMPT66047.pdf), [NSE ban publication](https://www.nseindia.com/static/products-services/equity-derivatives-risk-management-sec-ban). Declared applicability/increments do not establish complete margin coverage.
