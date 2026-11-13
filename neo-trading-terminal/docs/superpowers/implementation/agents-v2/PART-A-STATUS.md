# Part A resume

Plan: ../../plans/2026-11-13-remaining-part-a-sources.md
Baseline ca806c1. Main checkout codex/local-specialist-agents; preserve concurrent provider edits.

A1 interface implemented: SourceStamp and CapturedRiskBundle, frozen/extra-forbid, timezone-aware dates, strict positive owner, normalized existing position/rule contracts, duplicate/reference checks and conservative completeness gates. Five new contract regressions observed failing on absent module before implementation and then passed. A combined input regression command was started but its completion was not captured; do not claim that command passed.

A1 limits: fee_schedule retains the agreed dictionary extension point and needs an agreed typed dated schedule before production use. Frozen model fields do not recursively freeze nested dictionaries; caller must serialize/copy the bundle before storing/handing off private evidence. These must be addressed before A1 final acceptance; do not advertise the interface as fully immutable yet.

Next A2: diagnose authenticated holdings identity and positions/orders source failures using sanitized documented response shapes. A3 adjusted/pricing histories, A4 positioning history, A5 cash flows/fills, A6 B evaluator integration remain incomplete. B's evaluator does not exist in this checkout yet. Do not claim Part A complete. Existing signed-in backend was not restarted.
