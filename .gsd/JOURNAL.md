# Journal

## 2026-10-29 — Agent routing and MCP configuration

- Added authenticated unified chat with an Agno route-mode team; route selection happens before creation of the selected user-scoped private capability. Existing chain and portfolio chat endpoints and UI remain available.
- Added explicitly enabled HTTPS external MCP configuration, named tool and scope allowlists, environment-backed bearer credentials and per-run connection cleanup. Empty default configuration exposes no external tools. Operators must trust enabled services and their read-only declarations.
- Added same-provider backup API keys, one bounded retry for an explicit provider 429, and startup configuration of both Agno loggers with existing run-context suppression.
- Focused new-feature tests: 13 passed, including real Agno route-mode execution with a fake HTTP model transport. Offline options evaluation: 6/6, with no model evaluation. Frontend: 23 tests passed, lint and production build passed. `pip check` passed with an existing invalid-distribution warning.
- A full backend run started during an MCP prefix edit returned 253 passed and one test failure caused by reading different revisions during the run. The affected test passed in a fresh focused run; a final full suite was started afterward.
- Final full backend regression: `254 passed in 130.05s`. This fresh run used the corrected MCP prefix implementation and test.
- No live model, external MCP server, or broker verification was performed. Tree Ring recall could not run because no compatible local CLI was found.

## 2026-10-26 — First read-only options chat agent

- Added `/options-chat/` to the existing website, with market context controls, question suggestions, optional minute-by-minute snapshot refresh while visible, data limitations, and per-reply evidence timestamps.
- Added Agno 3.1.10/OpenAI 2.54.0 integration, a no-argument snapshot read tool, deterministic OI arithmetic, validated broker data, private SQLite conversation evidence and versioned run audit metadata. Tool calls, model output, concurrent requests and user request rates are bounded. No execution tools are available to the agent.
- Verification: backend full suite returned `101 passed, 1 warning in 40.97s` before the additional Agno-error-status regression test. Warning is the existing Starlette/AnyIO deprecation. Frontend `npm run lint` passed; `npm run build` successfully exported 14 pages including `/options-chat`.
- Browser verified a suggested question through a separate fixture-only server and database, with the resulting answer, OI totals, partial-chain ratio and premium rows visible. Screenshot: `neo-trading-terminal/docs/options-chat-preview.png`. Fixtures are explicitly identified in the preview answer and account name; they are not live market results.
- Server-side OPENAI_API_KEY was not configured. No paid model request, live broker verification, order submission, MCP server or production deployment is claimed. Setup and next milestones are documented in `neo-trading-terminal/docs/OPTIONS_AGENT.md`.
- Added regression coverage for Agno returning an ERROR run instead of raising; the final focused suite returned `17 passed, 1 warning in 6.75s`. Started the actual local application at `http://127.0.0.1:8000/options-chat/` and verified its sign-in screen; stopped the separate fixture preview afterward.

## 2026-10-22 — Unified Kotak sign-in and portfolio

- Added a single broker login screen (API key, UCC, mobile, TOTP, MPIN). Authentication creates/resumes a broker-verified user identity, sets an HttpOnly cookie and syncs holdings, positions, limits and orders before opening Portfolio & orders. Stale instrument listings refresh in the background. Connections is now a status/retry page.
- Consumer key/session remain server-side; MPIN/TOTP are not persisted. Broker-only identities are separate from the legacy local paper account. Sign-out disconnects the broker; expired sessions return to the login screen. Account refresh restores Kotak portfolio mode.
- Replaced shared-session manual live routes with current-user routing, explicit stock/derivative products, lot/tick/expiry checks, risk checks, durable request-ID replay protection and cancellation ownership checks. Added live order review in the ticket. Local manual execution is enabled; TRADING_MODE remains paper for automated strategies.
- Scoped quote/history/activity requests, paper price-source metadata, matching and WebSocket updates by user.
- Validation: full backend suite returned `83 passed, 1 warning in 33.17s`; warning is the existing Starlette/AnyIO deprecation. Frontend lint/type checking and production export passed. An intermittent OneDrive build-cache EPERM was resolved by preserving the generated cache under ignored `.test-runs/` and rebuilding.
- Browser: isolated simulated-broker server verified form login → imported holdings portfolio, opening the connected ticket, reviewing without submission, sign-out, and cookie-based restoration after reload. No console errors in that flow. Actual user portfolio permissions/authentication still require their current broker login. No real orders were submitted.
- Local website remains at http://127.0.0.1:8000/login/. Preview image saved as neodesk-login.jpg in this chat's visualization folder. Test output folders were moved into ignored `.test-runs/` for recovery.

> Previous milestone journal archived in `.gsd/milestones/v1.0/JOURNAL.md`

## 2026-10-07 — Instrument detail completion checks

- Fixed selected-period re-click loading state, controlled futures/options navigation, explicit empty-quote errors, cleared failed contract results, and moved quote-cache lock acquisition off the async event loop.
- Added prominent derivative symbol/expiry/lot identification and documented deliberately unavailable integrations.
- Backend: `pytest -q --basetemp=.pytest-tmp-detail-final-1007` returned `65 passed, 1 warning in 17.46s`. Default test temp directory was inaccessible; using a workspace-local directory resolved fixture setup errors.
- Frontend lint and production export passed. Browser confirmed Nifty area chart, re-clicked 1W remaining loaded, 22800 options returning CE/PE contracts, futures switch resetting filters, and the Nifty October futures detail/Technicals view. Browser error log was empty.
- Read-only HTTP: Kotak snapshots returned for HDFCBANK, Nifty 50, Bank Nifty and Sensex. Nifty 15-minute / 7-day history returned 75 candles, `partial: false`. No trades submitted.
- Remaining provider/product limitations: no claim of universal quote availability (Sensex50 previously returned no quote); snapshots are not tick streaming. Research/fundamental/news panels, alerts, SIP, GTT and five-year history remain unavailable.

---
