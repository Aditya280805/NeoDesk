# Analytics foundation review

Fresh read-only reviewer inspected da1262e and current additions. Fixed findings:

1. Reject nonfinite/bool/unknown-kind stress positions before arithmetic; never turn NaN cells into zero loss.
2. Continuation finish requires unique lease nonce; old worker cannot publish against reclaimed action.
3. Mixed-expiry surfaces require per-expiry forwards and rates.
4. Analytics discovery checks session generation; historical-report discovery remains independent.
5. Debit spread legs preserve and match canonical underlying, exchange and currency.
6. Evidence dispatcher requires candidates to match explicit captured evidence identity.

Regression tests live in backend/tests/test_analytics_v2.py. New calculation modules remain server-only and have no public request path until capture/orchestration is integrated. Missing planned capabilities are recorded in STATE.md, not represented as completed work.
