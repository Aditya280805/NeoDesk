# Read-only live validation — 2026-11-13

The user's continuation after the explicit read-only smoke-check request authorized these checks. Authorization persists; do not ask again merely to repeat this scoped validation. No order/execution, deployment or model-download authorization is implied.

## Verified local model behavior

Configured Ollama was stopped. Started the existing installed service on loopback, using the already installed qwen3.5:9b-q4_K_M. No model replacement/download or environment-file change.

Actual requests exposed Agno's default system->developer role mapping. The configured local model followed a direct system-role instruction probe, while analytics requests arrived with developer-role instructions and failed classification. An Ollama-only per-instance role_map now preserves system; cloud OpenAI mapping remains unchanged. A real SDK/mocked HTTP regression proved this boundary RED then GREEN.

Internal RouterIntent selects one category; trusted code creates exact ordered RoutingDecision roles. This removes inconsistent mode/role pairs and reduces generation. Local analytics use deterministic sampling, no repetition penalty, one model request and no backup retry. Router completion cap is128; specialist cap256. Public routing/evidence/result shapes are preserved. Coordinator version2 invalidates incompatible old continuations.

Canonical live scores during diagnosis: old1/20; compact intent3/20; deterministic sampling5/20; correct transport role17/20; clarified domain policy20/20. [Original report](router-live-2026-11-13.json) and [final canonical report](router-live-final-2026-11-13.json) retain actual results.

The separately authored heldout set first scored **9/10**, missing a combined volatility/levies request. After correcting the domain vocabulary, [that set's regression retest](router-live-regression-2026-11-13.json) scored10/10. The [initial heldout report](router-live-heldout-2026-11-13.json) is retained. The retest is no longer untouched heldout evidence; do not claim general100% model accuracy.

Specialist model output uses request-local enum references for up to32 scalar choices per consumed tool, four claims and sixteen proposal choices. Trusted code binds refs back to exact evidence IDs/paths and candidate proposal IDs; no new MCP call. Invalid/duplicate/unbound refs fail closed. Interpretation remains short, qualitative and validated. Numeric-text and length restrictions are represented in the generation schema as well as server validation. A synthetic real MCP/model smoke verifies numerical claims and released capabilities; [result](specialist-live-synthetic-2026-11-13.json). It does **not** verify real broker data or every specialist/question.

From backend, rerun explicitly when authorized:

```powershell
.venv-harness/Scripts/python.exe -m app.terminal.analytics_evals --mode live-model --progress --output ../docs/superpowers/implementation/agents-v2/router-live-final-2026-11-13.json
.venv-harness/Scripts/python.exe -m app.terminal.analytics_evals --mode live-model --dataset heldout --progress --output ../docs/superpowers/implementation/agents-v2/router-live-regression-2026-11-13.json
.venv-harness/Scripts/python.exe -m evals.live_specialist_smoke --live-model --output ../docs/superpowers/implementation/agents-v2/specialist-live-synthetic-2026-11-13.json
```

These scripts write sanitized summaries, not keys, capabilities or account envelopes. Offline router replay remains the default and cannot establish model quality. The specialist harness uses isolated synthetic sources and requires its live flag.

## Unavailable sources

No running authenticated app/backend session was available on this host; only Ollama was listening. Broker credentials being configured does not establish a signed-in individual owner. No user1 inference or authenticated broker call was made. Complete live broker/source adapter validation needs the terminal running with an individual account signed in.

The official NSE ban CSV link again timed out under a bounded public HTTPS probe. Do not infer the next effective trading date from download time or invent its schema. Official participant HTTP failures now preserve independent captured evidence while reporting only that tool unavailable; session, policy and deadlines still fail closed.

Remote CI and Docker remain unverified. Rollout flags remain default off. Full account-wide fee/margin/compliance and adjusted-history adapters remain tracked in COMPLETION-GAPS.md.
