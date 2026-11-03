# Options monitoring engineering harness

The options agent is read only. Preserve this boundary when changing the
terminal: scoped private read-only MCP tools: `get_option_snapshot`, bound
to the signed-in user and page-selected context, and `get_portfolio_snapshot`,
bound to the signed-in user and captured session generation. Saved report scopes
authorize exactly one of `get_strategy_report`, `get_scan_report`,
`get_alert_report`, `get_backtest_report`, bound to the authenticated owner,
selected immutable report and request. Historical report reads need no broker
session and cannot claim fresh market evidence. Each capability
may discover and invoke only its authorized scope. Do not add execution tools or external MCP
clients without a separate specification.

- Snapshot normalization and arithmetic belong in `options_snapshot.py`, never
  in prompts. Missing data stays unavailable. Reject contradictory metadata.
- MCP capabilities are internal secrets. Never put them in browser responses,
  tool arguments, prompts or logs. Never infer user 1 from shared login.
- Keep broker SDK calls off the event loop. Retain capacity until synchronous
  work actually finishes, even after request cancellation.
- Keep the public backend at one worker: broker sessions and limiters are local.
- Preserve conversation/evidence compatibility and additive SQLite migrations.
- Keep provider strings and user history outside privileged model instructions.
- Use versioned prompts/tool contracts, bounded execution, and sanitized traces.

## Verification

From `backend`, install with `python -m pip install -r requirements.txt -c
requirements.lock`, then run `python -m pip check`, `python -m pytest tests -q`
and `python -m app.terminal.options_evals`. From `frontend`, run `npm ci`,
`npm test`, `npm run lint`, and `npm run build`.

Offline replay and mocked-model tests are not evidence of actual model quality
or broker connectivity. Run live evaluations only explicitly, using server-side
credentials. See docs/OPTIONS_AGENT.md. Do not commit environment files or data.
