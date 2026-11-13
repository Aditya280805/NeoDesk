# Part A resume

Latest A2: authenticated diagnostics show holdings data array6, positions/orders envelopes with no data and no generic error keys; funds may legitimately use flat fields. Reference SDK tests/e2e/smoke_test.py documents exact integer stCode5203 + stat Not_Ok as no orders/trades/positions. Added conservative normalization to empty data only for positions/order_report, excluding contradictory data/error fields. Diagnostics now record documented_empty boolean without provider text. Actual live code5203 remains unconfirmed until new code runs; do not claim live portfolio failures fixed. No further restart performed. Verification source/service/normalization42 passed; next capture live documented_empty flag after controlled restart, then resolve holdings via private master crosschecks.

Backend restarted at user's explicit request with backend/logging-local.json enabling the allowlisted market diagnostics; health endpoint verified. Broker sign-in must be renewed. Inspect logs/restart-local.stderr.log only for portfolio_source_shape entries after refresh; never print unrelated raw SDK messages. Initial launch referenced the config before it existed and exited; config was added and successful launch then verified.

Plan: ../../plans/2026-11-13-remaining-part-a-sources.md
Baseline ca806c1. Main checkout codex/local-specialist-agents; preserve concurrent provider edits.

A1 interface implemented: SourceStamp and CapturedRiskBundle, frozen/extra-forbid, timezone-aware dates, strict positive owner, normalized existing position/rule contracts, duplicate/reference checks and conservative completeness gates. Five new contract regressions observed failing on absent module before implementation and then passed. A combined input regression command was started but its completion was not captured; do not claim that command passed.

A1 limits: fee_schedule retains the agreed dictionary extension point and needs an agreed typed dated schedule before production use. Frozen model fields do not recursively freeze nested dictionaries; caller must serialize/copy the bundle before storing/handing off private evidence. These must be addressed before A1 final acceptance; do not advertise the interface as fully immutable yet.

Next A2: diagnose authenticated holdings identity and positions/orders source failures using sanitized documented response shapes. A3 adjusted/pricing histories, A4 positioning history, A5 cash flows/fills, A6 B evaluator integration remain incomplete. B's evaluator does not exist in this checkout yet. Do not claim Part A complete. Existing signed-in backend was not restarted.

A2 diagnostic instrumentation: Market.call now emits only allowlisted envelope/data type, bounded row count, known identity field names and presence of known error keys for four portfolio methods. No raw account values, provider messages, arbitrary keys, owners or credentials are logged. New privacy/envelope regressions first failed on absent helper.40 source/service/normalization tests passed in13.60s. Current server predates instrumentation; observing it requires a backend restart and broker reauthentication, which has not been performed.
