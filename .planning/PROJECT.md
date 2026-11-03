# PROJECT.md — NeoDesk Multi-User Kotak Portfolio

> **Milestone**: v4.0 (Multi-User Authentication & Private Portfolios)
> **Status**: `IN_PROGRESS`

## Vision
Transform NeoDesk from a single-user personal terminal into a multi-user platform where each user signs up via a public website, manages their own private portfolio of Indian market instruments, and optionally connects their own Kotak Neo API credentials for real market data. All user data (watchlists, paper trades, strategies, Kotak sessions) is isolated per-user. Real-money order execution remains disabled.

## Goals
1. **Public Signup & Auth**: Email/password registration, bcrypt password hashing, JWT session tokens, login/logout with rate limiting.
2. **Per-User Data Isolation**: Every DB table scoped by `user_id`. Each user's watchlist, paper account, orders, strategies, and signals are private.
3. **Per-User Kotak Sessions**: Each user can connect their own Kotak consumer key and login with their own TOTP/MPIN. Sessions stored in-memory keyed by user_id.
4. **Private Portfolios**: Holdings, paper P&L, and strategy bots visible only to their owner.
5. **Real-Money Order Execution Disabled**: All live trading endpoints remain hard-disabled. The platform is for paper trading and market data only.

## Non-Goals (Out of Scope)
- OAuth/social login (email+password only for now).
- Admin panel or role-based access.
- Real-money live order execution.
- Multi-tenant SaaS billing.

## Users
Multiple registered users, each with their own paper trading account and optional Kotak Neo connection.

## Constraints
- Backward compatibility: existing single-user data should continue to work (migrated to user_id=1 as the "legacy" user).
- Preserve all existing uncommitted holdings-page changes.
- SQLite remains the database (WAL mode). user_id is added as a column, not separate DBs.
- Frontend must work as a Next.js static export served by FastAPI.

## Success Criteria
- [ ] A new user can sign up via the public website with email + password.
- [ ] Each user sees only their own watchlist, positions, orders, and strategies.
- [ ] Each user can independently connect their own Kotak API key and login.
- [ ] No user can access another user's data through any API endpoint.
- [ ] Real-money order execution remains hard-disabled in code.
- [ ] Existing backend tests pass (adapted for multi-user context).
