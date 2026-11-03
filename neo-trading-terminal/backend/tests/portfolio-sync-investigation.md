# Portfolio sync investigation — 2026-10-22

Status: partial fix verified; real broker retry pending.

The reported screen shows successful authentication followed by a positions request failure. `snapshot` previously called four broker endpoints without isolating failures; a positions failure discarded the already retrieved holdings and prevented funds and orders from being requested.

The snapshot now validates and fetches each section independently. Section failures are explicitly returned in `section_errors`; failed holdings totals are null, not zero. Authentication expiry still aborts the snapshot. The frontend displays available sections and distinguishes unavailable sections from genuinely empty accounts.

Tests reproduce positions rejection and malformed order responses while confirming holdings remain available. Holdings failure also preserves funds without manufacturing holdings totals. Existing expiry and account-isolation tests remain in place.

The upstream reason for the user's positions rejection remains unconfirmed. There was no accessible signed-in browser tab during investigation, and the SDK's error was sanitized by the application. Do not claim the real broker response has been repaired or invent empty positions from an arbitrary broker error. The user needs to retry the updated application with their own current login.
