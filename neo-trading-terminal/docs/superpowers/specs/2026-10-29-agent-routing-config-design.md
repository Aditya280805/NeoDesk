# Agent routing, MCP configuration and provider resilience

Status: implementation requested by the user. The request replaces the earlier single-agent
direction for unified routing; existing per-user evidence boundaries remain.

## Design

1. Add a validated `mcp.json` registry for explicitly enabled external servers.
   Resolve credentials from server environment variables, never configuration
   literals. External servers are untrusted: require administrator allowlists,
   named read-only tools and explicit authorization before connecting. Keep the
   private portfolio/options MCP separate. Configuration alone cannot guarantee
   compatibility or authorization for arbitrary third-party servers.
2. Introduce `KeyRotator` for same-provider configured primary and backup keys.
   Rotate only on a recognized rate-limit response, with bounded attempts and
   a shared per-run deadline and token budget. Do not fail over on authentication,
   malformed responses or ambiguous failures. Never log credential values.
3. Make `setup_agno_logging` configure both Agno loggers with credential-safe
   filtering, idempotently and without disabling existing application logging.
   Preserve current per-run exception suppression and test handler propagation.
4. Provide one authenticated chat endpoint with route-based delegation to the
   existing options and portfolio specialists. Routing chooses a scope, then the
   server binds user identity and the corresponding private MCP capability;
   model selection must never grant access across scopes. Unknown, mixed or
   ambiguous requests request clarification. Preserve existing endpoints and
   conversation/evidence contracts. Verify the installed Agno Team API before
   selecting the implementation and retain deterministic authorization outside it.

## Verification

Test configuration rejection, secret handling, MCP allowlisting, rate-limit-only
failover, exhausted keys, logging redaction, scope isolation, ambiguous routing,
conversation compatibility, deadlines and both provider integrations. Run the
backend suite and offline evaluation commands. Live provider and third-party MCP
checks require actual configured services and are reported separately.
