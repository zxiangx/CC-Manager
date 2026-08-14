# Session-Owned Codex State Design

## Objective

Decouple Codex conversation state from account credentials. Each native Codex
account keeps its own authentication/configuration directory, while every CCM
Task sees one shared rollout and SQLite state store. Switching a Task's account
therefore changes only its credential route and never copies its context or
Goal into another account directory.

## Storage model

CCM owns one private shared runtime root, configured by
`CODEX_SHARED_STATE_DIR` and defaulting to `~/.ccm/codex-state`:

```text
~/.ccm/codex-state/
├── sessions/             # the only active rollout tree
├── archived_sessions/    # the only archived rollout tree
├── state_*.sqlite        # Codex thread/runtime index
└── goals_*.sqlite        # the only native Goal database
```

Each account retains its private `auth.json`, `config.toml`, model cache, and
login artifacts. Its `sessions` and `archived_sessions` paths are private
symlinks to the CCM shared store. Every app-server receives the same absolute
`CODEX_SQLITE_HOME`, while `CODEX_HOME` continues to point at the selected
account so OAuth refresh and account-specific provider configuration remain
isolated. OpenAI documents these as separate supported locations: `CODEX_HOME`
contains auth and sessions, while `CODEX_SQLITE_HOME` selects SQLite-backed
runtime state.

The app-server registry still owns a strict `thread_id -> account home` route
for live process safety. Rebinding an idle thread changes only that in-memory
owner and the Task's durable `codex_account_id`; it does not copy files.

## Legacy convergence

Explicit user-confirmed Goal authorities for the production migration:

- Task 13 / thread `019ffae1-eb08-7242-a1a7-3233c8eaff15`: `codex-2`
- Task 17 / thread `019ff47e-5c36-79a3-b730-48517bceb122`: `codex-2`
- Task 37 / thread `019ffbf6-cf8c-71c0-970e-774b0dfe5b3d`: `codex-7`

These overrides win over timestamps and rollout ownership. Every account-local
Goal database remains in place as legacy evidence; app-servers write only to
the new shared SQLite home after cutover.

Startup runs a fail-closed, idempotent convergence before Dispatcher admission:

1. Build the shared root with owner-only permissions.
2. Scan native/API account homes for legacy rollout copies.
3. For identical or prefix-related copies, retain the longest valid rollout.
4. For diverged copies, prefer the Task's currently bound account. Move the
   winner into the canonical store and every rejected copy into a timestamped
   owner-only backup directory, preserving all evidence without duplicating
   multi-gigabyte rollout files.
5. Merge native Goals by `thread_id`, retaining the row with the latest
   `updated_at_ms`; rejected rows remain in the backup.
6. Write a private phase plan, move each legacy
   `sessions`/`archived_sessions` directory to backup, install the canonical
   directories, then project account symlinks.
7. Record a completion marker. If the process is interrupted, the next startup
   resumes from the durable phase plan instead of re-copying or discarding data.

No source is deleted. An unsafe file type, symlink, ownership mismatch, SQLite
schema mismatch, or unresolvable copy conflict aborts startup before tasks run.

## Account selection

- New Tasks bind to the configured default/global account at creation/admission.
- A Task-level **切换** action changes only the current Task's binding.
- **全局切换** changes the default account and schedules all existing Codex
  Tasks to converge. Idle Tasks switch immediately; active Tasks switch after
  their current native turn reaches a confirmed boundary.
- A Task binding is authoritative. Global defaults never silently rewrite it
  except as part of an explicit global-switch operation.
- API accounts remain selectable manually, but automatic capacity rotation
  never selects API/CloudRouter/Apex accounts.

## Capacity policy

Capacity failures are tracked by `(task_id, account_id)` rather than instance.
Only observations at least three minutes apart count. On the third consecutive
observation, CCM chooses a random compatible native OAuth account with known
remaining quota, excluding the current account and every account already tried
in the current rotation cycle. It rebinds the idle thread and immediately
retries the same queued message. Further capacity failures rotate through the
remaining candidates. When all candidates have been tried, CCM starts a new
cycle after the normal three-minute delay. Success, a user-selected account,
or a non-capacity terminal resets the tracker.

The UI and task event stream disclose the old/new account, retry count, next
retry time, and rotation reason. Account changes never masquerade as context
migration.

## Pool UI

The Codex account card removes the **重新登录** action. When a Codex Task is the
current route, each account exposes **切换** for that Task. Every account also
exposes **全局切换**, which changes the default and converges all Tasks. Outside
a Task route, **切换** is disabled with a concise explanation; **全局切换**
remains available. Existing account-add, quota refresh, cooldown, and delete
flows remain unchanged.

## Verification

- Unit tests cover shared-store convergence, divergent backup behavior,
  canonical Goal selection, idempotence, and unsafe-path rejection.
- Dispatcher/API tests prove Task-only and global bindings, safe active-turn
  deferral, and no rollout migration calls.
- Capacity tests use a deterministic random source and fake clock to prove the
  three-minute/three-observation threshold, OAuth-only filtering, no repeats
  within a cycle, reset on success, and retry continuity.
- Frontend tests verify button labels, removal of relogin, current-Task switch
  calls, global-switch calls, and disabled behavior outside a Task.
