# Disable Remote CCM Updates

## Goal

Allow a deployment to hide all remote-update UI and stop update discovery without deleting the existing updater. Manual deployment of local code and ordinary service restarts must keep working.

## Design

Add a `REMOTE_UPDATES_ENABLED` deployment setting, defaulting to `true` for backward compatibility. `/api/system/config` publishes the capability. The application shell starts with updates disabled and mounts `UpdateButton` only after the server explicitly returns `true`; this fail-closed behavior prevents update checks, prompts, and button flashes when the capability is disabled or unavailable.

Update, repair, reconcile, and rollback mutations reject requests while disabled. The standalone restart endpoint remains available because it does not fetch or install remote CCM code.

Production sets `REMOTE_UPDATES_ENABLED=false`. Re-enabling later requires only changing that environment value and restarting CCM.

## Verification

- Backend tests verify the capability response, blocked update mutations, and retained restart behavior.
- Frontend tests verify the button appears only when explicitly enabled and stays unmounted when disabled.
- Build the frontend and confirm the production config endpoint reports `false` after deployment.

## Session Pinning

CCM already persists a `starred` task group and orders that group ahead of all other sessions. Reuse that stable storage and ordering contract, but expose it consistently as “Pin session” in the task list, compact sidebar, chat header, creation form, and filter. This avoids a redundant database field while giving the existing behavior the requested, discoverable meaning. Unpinned sessions retain their existing latest-conversation ordering.
