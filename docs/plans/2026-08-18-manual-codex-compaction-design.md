# Manual Codex context compaction

CCM will expose one explicit `Compact` control in the local Codex chat
composer. The control is available only when the Task already owns a native
Codex thread, Codex app-server mode is enabled, and CCM does not believe the
Task is running. Clicking it calls a task-scoped CCM endpoint; it does not add
a user message or invoke CCM's legacy summary-and-session-rotation path.

The backend resolves the Task's exact persisted `threadId` and bound
`CODEX_HOME`, then sends `thread/compact/start` to that account's existing
app-server transport. Admission is serialized with other Task mutations and
with the app-server registry's per-thread operation fence. Active turns,
rebindings, account maintenance, and mismatched account ownership fail closed
with a conflict response. The native RPC returns immediately after Codex
accepts the compaction; completion continues through Codex's normal
`turn/*`/`item/*` lifecycle, including the `contextCompaction` item.

The UI labels success as “started,” not “completed,” because the native RPC is
asynchronous. While the HTTP request is in flight the button is disabled and
shows a spinner. A rejected request leaves the thread untouched and displays
the server error through the existing composer error surface. The feature is
covered at four boundaries: raw app-server RPC shape, registry/InstanceManager
routing, task API authorization and conflict mapping, and the composer button's
visibility, disabled state, and click behavior.
