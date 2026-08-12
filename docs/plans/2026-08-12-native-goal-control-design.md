# Native Goal control design

## Objective

Make Codex native Goals permanently discoverable in CCM and give the user one
explicit cancellation operation. A Goal that has not been cancelled must not
be silently replaced by an ordinary chat turn after a pause or transient
capacity failure.

## Source of truth

Codex app-server remains the only Goal store. CCM reads `thread/goal/get` every
time the panel opens (and periodically while the chat is visible), so a page
reload, Task switch, or CCM restart does not depend on a transient chat event.
The returned object contains the objective, lifecycle status, token usage,
budget, elapsed time, and timestamps.

No second database copy is introduced. Two writable copies would create an
ambiguous cancellation/recovery state; the native thread already persists the
Goal independently of CCM's process adapter.

## Operations

- `GET /api/tasks/{id}/native-goal` resolves the Task's exact Codex account
  home and returns the native Goal or `null`.
- `DELETE /api/tasks/{id}/native-goal` first runs CCM's exact-generation stop
  path. This pauses and interrupts a currently followed Goal turn without
  disturbing other Tasks on the shared app-server. It then calls
  `thread/goal/clear` and performs a second `thread/goal/get`; success is only
  returned after absence is proven.
- Both routes reuse Task access/control permissions and Worker proxy routing.

## Continuation semantics

`paused` means the user interrupted execution, not that the Goal was cancelled.
`blocked` can also be produced by a transient failed autonomous turn (including
model capacity). Standard admission therefore restores either state to
`active`, waits for the exact native Goal turn, and steers the pending message
or retry into that turn. `usageLimited`, `budgetLimited`, and `complete` retain
their native meanings and are never bypassed.

Explicit cancellation is the only CCM action that clears the Goal. After it is
cleared, later messages are ordinary turns and no Goal continuation can start.

## UI

Codex chats with a native thread show a Goal button in the header. Its status
dot is refreshed in the background. The modal shows the complete objective,
status, usage, budget, elapsed time, and timestamps. Cancellation uses a
two-click confirmation and keeps any failure visible; the UI only switches to
“no Goal” after the backend confirms the clear.

## Verification

- Protocol tests cover paused and blocked reactivation, confirmed clear, and
  idempotent clear when no Goal exists.
- API tests cover persistent reads and stop-before-clear cancellation ordering.
- The complete app-server and Task API suites plus the production frontend
  build must pass before deployment.
