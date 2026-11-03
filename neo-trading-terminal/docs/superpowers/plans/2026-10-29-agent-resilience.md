# Agent Resilience Implementation Plan

**Goal:** Add bounded provider failover, safe logging, external MCP configuration and unified specialist routing.

**Architecture:** Preserve existing evidence and user-scope enforcement. Retry only recognized rate limits within the existing model instance's budget. Route before creating scoped private MCP capabilities.

**Tech Stack:** Python, FastAPI, Agno, MCP, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-agent-routing-config-design.md`.

## Tasks

- [x] Add rate-limit-only key rotation for both providers, with bounded requests and redacted keys. Test recognized 429, other errors and exhausted keys.
- [x] Configure both framework loggers idempotently, retaining existing handlers and filtering secrets. Test both loggers.
- [x] Validate declarative MCP server definitions and connect only explicitly allowed tools without crossing private scope. Test invalid definitions and lifecycle.
- [x] Implement authenticated unified chat with route-mode team selection, fail-closed ambiguity and scoped execution. Test route choices and evidence isolation.
- [x] Run backend tests, dependency checks and offline evaluations. Document configuration and limitations.
