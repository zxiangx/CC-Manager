# Session-Owned Codex State Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep one authoritative Codex context/Goal store per CCM deployment while allowing each Task to select an independent account and safely rotate native OAuth accounts after repeated capacity failures.

**Architecture:** Account homes retain credentials and provider config; shared rollout directories plus `CODEX_SQLITE_HOME` hold native thread state. Task bindings select an account app-server without copying context. A persisted global default is separate from explicit Task bindings.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, SQLite, Codex app-server JSON-RPC, React 19, TypeScript, Vitest.

---

### Task 1: Shared Codex state convergence

**Files:**
- Create: `backend/services/codex_shared_state.py`
- Modify: `backend/config.py`
- Modify: `.env.example`
- Modify: `backend/main.py`
- Test: `backend/tests/test_codex_shared_state.py`

**Steps:**
1. Write failing tests for private-root creation, rollout prefix selection,
   diverged-copy backup, latest Goal selection, symlink projection, and
   idempotent restart.
2. Run `uv run pytest backend/tests/test_codex_shared_state.py -q` and confirm
   the new service is missing.
3. Implement fail-closed convergence and the completion manifest.
4. Wire convergence before Dispatcher startup and expose the shared state path
   through Settings.
5. Re-run the focused tests and confirm they pass.

### Task 2: Shared app-server state and copy-free rebind

**Files:**
- Modify: `backend/services/codex_app_server.py`
- Modify: `backend/services/instance_manager.py`
- Modify: `backend/services/dispatcher.py`
- Modify: `backend/services/codex_session_migration.py`
- Test: `backend/tests/test_codex_app_server.py`
- Test: `backend/tests/test_service_dispatcher.py`

**Steps:**
1. Write failing tests proving every account app-server receives the same
   `CODEX_SQLITE_HOME` and account rebind never copies a rollout.
2. Add the shared SQLite path to app-server construction and environment.
3. Replace migration-before-rebind with shared-state owner rebind and fenced
   Task-binding commit.
4. Retain the legacy migration helper only for startup convergence and remote
   Worker import compatibility.
5. Run focused app-server and Dispatcher tests.

### Task 3: Per-Task and explicit global account APIs

**Files:**
- Modify: `backend/api/codex_pool.py`
- Modify: `backend/services/codex_pool.py`
- Modify: `backend/services/dispatcher.py`
- Modify: `frontend/src/api/client.ts`
- Test: `backend/tests/test_codex_pool_api.py`
- Test: `backend/tests/test_service_dispatcher.py`

**Steps:**
1. Write failing API tests for `POST /codex-pool/tasks/{task_id}/account`
   and `POST /codex-pool/global-account`.
2. Implement Task-only binding with idle-thread rebind and active-turn deferred
   convergence.
3. Make global selection update both the new-Task default and an explicit
   batch-convergence generation.
4. Remove implicit global convergence from ordinary account selection and
   quota completion.
5. Run focused API and Dispatcher tests.

### Task 4: Capacity rotation

**Files:**
- Create: `backend/services/codex_capacity_rotation.py`
- Modify: `backend/config.py`
- Modify: `backend/services/instance_manager.py`
- Modify: `backend/services/dispatcher.py`
- Test: `backend/tests/test_codex_capacity_rotation.py`

**Steps:**
1. Write fake-clock tests for three observations separated by 180 seconds.
2. Test that API accounts, exhausted accounts, incompatible models/tiers, and
   already-tried accounts are excluded.
3. Implement deterministic-in-tests/random-in-production candidate selection
   and per-Task cycle state.
4. Rebind and retry without rollout copying; broadcast capacity/rotation state.
5. Reset state on success, manual switch, cancellation, and non-capacity error.

### Task 5: Codex Pool UI

**Files:**
- Modify: `frontend/src/components/Layout/PoolDrawer.tsx`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/components/Layout/PoolDrawer.test.tsx`

**Steps:**
1. Write failing tests asserting that Codex cards no longer show **重新登录**.
2. Add **切换** for the Task parsed from the active route and
   **全局切换** for every eligible account.
3. Disable Task-only switching outside a Task route; keep global switching.
4. Show current Task account and global default as separate badges.
5. Run the PoolDrawer tests and TypeScript checking.

### Task 6: Regression and build verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: `PROGRESS.md`

**Steps:**
1. Run focused backend tests from Tasks 1-4.
2. Run the full Codex pool/app-server/Dispatcher backend test groups.
3. Run `npm test -- --run frontend/src/components/Layout/PoolDrawer.test.tsx`.
4. Run frontend typecheck and production build.
5. Record migration/deployment requirements and results in `PROGRESS.md`.

