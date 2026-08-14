# Codex capacity backoff message handling

## Problem

When a Codex chat turn fails with `serverOverloaded`, CCM keeps retrying the
same turn every 60 seconds. Between attempts there is no native root turn, but
the per-task queue still owns the failed message. The UI currently calls this
`launch_queued` and says the turn has not started, even though it already ran
and is waiting for a capacity retry.

The composer also treats every processing state without a steerable root turn
as a client-side queue state. A message sent during capacity backoff is stored
only in browser `localStorage`. An unbounded capacity retry can therefore block
that message forever, and another device cannot see it.

## Design

InstanceManager exposes an exact task-scoped capacity-backoff record containing
the instance, retry attempt, delay, and a supersede event. The record exists
only while the failed turn is sleeping before its next retry. It is cleared
before relaunch, on cancellation, and on every terminal path.

The task capability endpoint returns this state separately from generic queue
work. The UI renders it as “model capacity unavailable; waiting to retry” and
does not claim that the turn has never started.

When a real user message is accepted by the server during this exact backoff
window, the chat API first commits its user log, Dispatcher then puts the work
item in the server-side per-task queue, and only after that signals the old
retry to stop. The old failed turn is settled as superseded at a provider-safe
boundary, its instance ownership is released, and the serialized queue
launches the newly persisted message. Monitor and automatic messages do not
supersede a user turn.

The composer bypasses its browser-only queue only for the proven capacity
backoff state. Active root turns still use native `turn/steer`; other busy
states retain existing behavior. This keeps one writer per Codex thread while
preventing an infinite retry from starving a newer user instruction.

## Verification

- Unit-test registering, exposing, superseding, and clearing a capacity wait.
- Verify Dispatcher signals supersede only after a user message is queued.
- Verify the capability endpoint reports the distinct state.
- Verify ChatView sends through `/chat`, shows the capacity message, and does
  not create a browser-local queued item.
- Run focused backend and frontend suites plus static type/build checks.
