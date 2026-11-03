# Product review — 23 October 2026

## Completed in this review

- Added light-theme overrides for navigation, tables, labels, inputs, selected controls, alerts, portfolio and instrument detail surfaces. Financial gain/loss colors use darker shades on light backgrounds.
- Made both historical chart components respond to the resolved theme, including axis labels, grid and indicator colors.
- Fixed the theme toggle when the current preference resolves through the operating system.
- Kept successful order submission feedback separate from a failed subsequent balance refresh. Included the paper/live endpoint in the order retry key so retries do not share identities across modes.

## Verification

- Backend: 85 tests passed; one existing Starlette/AnyIO deprecation warning.
- Frontend: ESLint, TypeScript and production export passed.
- Isolated browser fixture: successful sign-in, portfolio values, light-mode table text, instrument detail empty-history state, desktop/mobile layout and switch back to dark. No browser console errors observed. Used simulated broker responses, not a real account. Chart rendering with real historical data and real order execution were not tested.

## Priorities still outstanding

1. **Verify the real portfolio connection.** The earlier positions rejection is still not explained by an actual broker response. Section isolation prevents it from hiding holdings, but does not repair the upstream rejection. Add sanitized endpoint diagnostics, per-section last-success times, and explicit retry/backoff behavior.
2. **Review automated live strategies before enabling them.** `backend/app/terminal/engine.py` still uses `self.market.broker.client.place_order` while manual orders use the current user's session. Its order recording and audit calls also need review against the current store schema. Keep automated strategies in paper mode until this separate path is corrected and tested for account isolation, rejection handling and duplicate submissions.
3. **Improve order reconciliation.** Show submitted, acknowledged, partially filled, filled and rejected states with broker reasons; refresh status after uncertain network outcomes. Do not infer execution from a submission acknowledgement.
4. **Improve discovery.** Default to tradable equities, separate ETFs/debt/derivatives, provide recent searches and favorites, and label exchange, expiry and lot size clearly. The generic picker currently includes indices and OTHER instruments even though those cannot be ordered directly.
5. **Make data freshness prominent.** Distinguish live, last available, market closed, stale and disconnected states consistently across charts and tickets. Consolidate overlapping portfolio polling and suspend background polling on hidden tabs.
6. **Prepare deployment separately.** Validate production authentication configuration, persistent storage, backups, per-user access checks and restart/reconnection behavior before publishing to Render. Passing the existing tests is not a production security audit.

This was a focused theme and workflow review, not an exhaustive audit. Alerts, SIP, GTT, fundamentals/news integrations and TradingView/Pine execution remain separate unfinished features.
