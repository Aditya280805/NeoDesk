# Acceptance and release gates — 2026-11-13

P0–P11 are not fully accepted. Offline tests establish the behavior below; they do not establish live data availability or model quality. No percentage estimate substitutes for this matrix.

| Phase | Implemented and exercised locally | Remaining acceptance evidence/work |
| --- | --- | --- |
| P0 | Strict versioned contracts; durable resume records | None for foundation slice |
| P1 | Owner-bound immutable inputs, additive cache, chain/depth/master identity, broker daily history, typed imports | Automatic authenticated adjusted asset/benchmark/IV histories, fills/cash-flow mappings and verified rule/fee/margin input adapters remain incomplete |
| P2 | Role capabilities, isolation, two-read budgets including prefetch, deadlines, retained cancellation capacity, sanitation | Live runtime/latency checks |
| P3 | TA-Lib indicators/regimes, session VWAP, daily-basis VIX guard, bounded history/import path | Actual historical/VIX coverage; one 180-calendar-day batch may not support EMA200 |
| P4 | Black76/IV/Greeks, expiry-specific forward/rate inputs, surfaces, mounted dated IV history/RV | Automatic authoritative pricing/IV-history/actual-expiry sourcing and live fixtures |
| P5 | OI/PCR/walls/pain/buildup with provided previous OI/price, GEX proxy, declared synchronized cash/future basis, participant acquisition/history | Automatic prior-OI/cash-futures basis/complete participant-session and cash-flow histories |
| P6 | Server candidates inside existing payloads; no third MCP call; gross payoff, statutory fees, bound conditional costs | Complete dated broker/exchange/closing/exercise schedules, contract-note reconciliation, settlement/exchange timestamp proof |
| P7 | Ratios, beta/alpha, cash HRP/correlations/HHI, declared trades and sector allocation | Authenticated adjusted cash/trade/cash-flow adapters and sector performance attribution remain incomplete |
| P8 | Risk-only derived account report, dated lot/ban/FutEq scenarios, ELM/calendar applicability and conditional ELM increment, supplied-position post-proposal stress | Official dated ban/MWPL acquisition, verified account-wide/intraday FutEq/limits, complete calendar/SPAN/broker margin and complete-account aggregation remain incomplete |
| P9 | 28-cell repricing; per-series/per-horizon tails; independent 95% >=250 and 99% >=1000 availability | Verified representative production history/input coverage |
| P10 | Classifier, ordered stages, typed handoff, evidence rendering, fenced/idempotent two-resume continuation | Live router/model quality evaluation; offline replay checks contracts only |
| P11 | Responsive opt-in UI, evidence/missing inputs, session fences, independent default-off flags, CI definitions, docs, synthetic browser checks | Remote CI, Docker on available host, live smoke validation and release approval |

Internal work is distinct from external validation: adapters/calculations explicitly named above remain implementation work. Missing-data behavior and declared scenarios are not verified production coverage.

Source probe: the official NSE page links `https://nsearchives.nseindia.com/content/fo/fo_secban.csv` for the next trade date. A bounded public HTTPS probe on this host timed out. Its current schema/effective trading date has not been validated; do not infer a date from download time or invent a header/parser to claim complete ban coverage. A dated representative publication is needed for that adapter.

Live credentials are a separate gate. AGENTS.md requires explicit live evaluation authorization; no broker/model credentials were used here. Obtain read-only broker/model smoke authorization plus sanitized representative source fixtures and authoritative dated schedules before completing those paths. Never place orders or enable execution.

Default rollout: ANALYTICS_TOOLS_ENABLED=false, ANALYTICS_ADVISORY_ENABLED=false, ANALYTICS_COMPOSITE_ENABLED=false. Tools enable snapshots; advisory additionally enables eligible hypothetical candidates; composite additionally enables unified analytics chat/UI.

Official references: [NCL expiry ELM](https://nsearchives.nseindia.com/content/circulars/CMPT64639.pdf), [index calendar rule](https://nsearchives.nseindia.com/content/circulars/CMPT66047.pdf), [NSE ban publication](https://www.nseindia.com/static/products-services/equity-derivatives-risk-management-sec-ban). Declared applicability/increments do not establish complete margin coverage.
