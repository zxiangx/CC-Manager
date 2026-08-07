# Monitor Feature Switch Implementation Plan

1. Add a default-off `codex_monitor_enabled` column and runtime settings schema.
2. Centralize the effective global gate so API, skill context, task validation,
   process launch, and MCP handlers use the same value.
3. Make Monitor capability checks require both the global gate and the existing
   exact Codex task-scope checks.
4. On disable, atomically cancel running local CCM Monitor rows, then stop their
   processes, clean generated configs, and broadcast status changes.
5. Add an administrator toggle to the preferences menu and wire it to the
   runtime settings API.
6. Add backend and frontend regression tests for default-off, on/off exposure,
   fail-closed creation, cleanup, and UI interaction.
7. Run focused suites, then the broader relevant backend/frontend checks before
   deployment.

