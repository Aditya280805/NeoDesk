# ROADMAP.md — NeoDesk v4.0 Multi-User

> **Current Milestone**: v4.0 (Multi-User Authentication & Private Portfolios)
> **Goal**: Public website signup, separate user data and Kotak sessions, private portfolios. Real-money order execution stays disabled.

## Must-Haves
- [x] User registration (email + bcrypt-hashed password) and JWT session authentication.
- [x] Per-user data isolation across all DB tables (watchlists, accounts, orders, positions, strategies, signals).
- [x] Per-user Kotak Neo API key and broker session management.
- [x] Private portfolio views — each user sees only their own data.
- [x] All existing tests adapted and passing.
- [x] Live order execution remains hard-disabled.

## Phases

### Phase 1: User Authentication System
**Status**: ✅ Complete (73 tests passing — 65 existing + 8 new auth tests)
**Objective**: Add user registration, login, JWT-based session management, and protect all API endpoints behind authentication. Replace the single `APP_PASSWORD` gate with per-user email+password auth.

**Tasks**:
1. Create `users` table (id, email, password_hash, display_name, created_at).
2. Add `bcrypt` and `PyJWT` to requirements.txt.
3. Create `app/auth/` module with registration, login, JWT issue/verify, and current-user dependency.
4. Create `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, `/api/auth/logout` endpoints.
5. Refactor the `protect` middleware to validate JWT tokens instead of APP_PASSWORD cookies.
6. Add rate limiting on registration and login.
7. Write tests for auth flows.

### Phase 2: Database Schema Migration & Per-User Data Isolation  
**Status**: ✅ Complete (74 tests passing including test_user_isolation)
**Objective**: Add `user_id` foreign key to all data tables, migrate existing data to a default user, and scope every Store method by user_id.


**Tasks**:
1. Add `user_id` column to: `account`, `positions`, `futures_positions`, `orders`, `watchlist`, `strategies`, `signals`, `audit`.
2. Create schema migration logic in Store.__init__ to add columns and backfill existing rows with user_id=1.
3. Refactor every Store method to accept and filter by `user_id`.
4. Refactor PaperAccount to pass `user_id` through all operations.
5. Initialize a fresh paper account for each new user on registration.
6. Update all API routes to extract user_id from JWT and pass to Store/PaperAccount.
7. Write tests verifying cross-user data isolation.

### Phase 3: Per-User Kotak Sessions & Frontend Multi-User UI
**Status**: ✅ Complete
**Objective**: Allow each user to independently connect their own Kotak API credentials. Update frontend with signup/login UI and per-user data display.

**Tasks**:
1. Refactor Market class to support per-user broker instances (dict keyed by user_id).
2. Refactor `/api/connection`, `/api/connection/login`, `/api/instruments/sync` to be user-scoped.
3. Update StrategyEngine to use per-user market/broker instances.
4. Frontend: Replace single-password login with email/password signup+login forms.
5. Frontend: Update API client to use JWT Bearer token from localStorage.
6. Frontend: Update Layout sidebar to show user email/display name.
7. Ensure demo mode works for users without Kotak credentials.

### Phase 4: End-to-End Verification & Hardening
**Status**: ✅ Complete (76 tests passing, Next.js build clean)
**Objective**: Validate multi-user isolation, verify live execution is disabled, run full test suite, and harden security.

**Tasks**:
1. E2E test: two users with separate portfolios, watchlists, and strategies cannot see each other's data.
2. Verify all `/api/live/*` endpoints remain hard-disabled (return 401/403 or are guarded).
3. Security audit: no user can enumerate/access another user's resources by ID manipulation.
4. Update .env.example with new multi-user config options.
5. Update README.md with multi-user setup instructions.
6. Run full test suite and fix any regressions.
