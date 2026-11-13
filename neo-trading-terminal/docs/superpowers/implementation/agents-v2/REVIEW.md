# Analytics foundation review

## Live validation and bounded choices — 2026-11-13

Actual local model testing exposed ignored developer-role instructions, malformed/truncated specialist output and unreliable copied evidence references. Ollama now preserves system on the wire (mocked real-SDK regression RED→GREEN), routing uses a compact typed intent and claims/proposals use enums resolved from consumed immutable evidence. Public IDs/paths/results stay server-derived and validated. No extra MCP read, retry or cloud fallback was added.

Fresh review found no blocking mathematical, privacy or binding issue in sector performance and bounded model selection. It identified existing thirty-price import coupling that prevented short sector histories; the two-date regression failed then passed after making HRP unavailable independently. Reviewer independently ran14 earlier tests and10 selection tests. Unknown/duplicate refs, raw model IDs/values and cross-binding attempts fail validation.

Full backend802 passed; explicit live-flag CLI guard tested separately. Canonical local live20/20, initial heldout9/10, corrected-case regression10/10, real-model/synthetic-source MCP smoke passed with four validated claims and one read. Initial failures and heldout distinction are documented in LIVE-VALIDATION.md. These checks do not establish broker connectivity, complete account coverage or general model correctness.

## Integration review — 2026-11-13

Fresh reviewer independently ran 26 focused integration tests and found no new authorization/execution boundary blocker. Identified VIX time-basis error: 20 intraday observations could masquerade as 20 daily observations. Regression observed failing, then fixed by withholding daily VIX z-score/regime unless aligned unique ordered Indian dates establish daily basis. Separate tests now cover mounted IV/RV history, cash correlation/HHI and independent tools/advisory/composite rollout switches. Previous source-expiry normalization and browser-safe paise findings were fixed with regressions. Account-source failure degradation was likewise demonstrated RED then GREEN.

Review acceptance gaps are tracked explicitly in COMPLETION-GAPS.md. No all-phase completion claim follows from offline tests. Declared costs, cash/future basis, margin increments and supplied-position stress retain scenario provenance; complete account/broker certification is unavailable. Concurrent provider-owned edits were preserved and excluded from this analytics commit.

Fresh read-only reviewer inspected da1262e and current additions. Fixed findings:

1. Reject nonfinite/bool/unknown-kind stress positions before arithmetic; never turn NaN cells into zero loss.
2. Continuation finish requires unique lease nonce; old worker cannot publish against reclaimed action.
3. Mixed-expiry surfaces require per-expiry forwards and rates.
4. Analytics discovery checks session generation; historical-report discovery remains independent.
5. Debit spread legs preserve and match canonical underlying, exchange and currency.
6. Evidence dispatcher requires candidates to match explicit captured evidence identity.

Regression tests live in backend/tests/test_analytics_v2.py. New calculation modules remain server-only and have no public request path until capture/orchestration is integrated. Missing planned capabilities are recorded in STATE.md, not represented as completed work.

## Authenticated capture and specialist-stage review

Fresh review of the next increment found and fixed:

- Publication could outlast cancellation/deadline/session eligibility while SQLite waited. Batch publication now runs under consistent market -> SQLite lock order, with deadline-bounded SQLite waiting and eligibility validation inside the transaction before commit. A failed validation rolls back the batch. Capture revalidates again before returning.
- Normalized source identity-verification caveats and limitations were discarded. Capture now preserves those as coverage and limitations, explicitly marks unknown identity and retains partial status. A real-normalizer fixture verifies absent provider identity metadata stays visible.

New tests cover blocked publication/session change/cancellation, atomic rollback, owner-bound captures, no event-loop broker work, real loopback MCP -> specialist -> rendered numeric claim, disabled-by-default/authenticated snapshot API, strict role sections, and sanitized errors.
