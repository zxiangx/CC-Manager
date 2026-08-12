# Goal idle gate and injected-message editing

## Goal semantics

An active native Codex Goal may start another root turn only after the whole
generation is quiescent. Quiescent means both the root turn and every native
collaboration descendant are idle. CCM pauses the native Goal when it observes
an active descendant and resumes it only after the last descendant becomes
terminal. The CCM process remains attached across the pause/resume boundary so
no continuation output is lost.

This is a lifecycle gate, not a second continuation engine. Codex remains the
only component that creates Goal continuation turns. CCM never injects a
synthetic "continue" prompt.

## Injected-message editing

An injected message is a same-turn steer, so Codex cannot fork at that exact
item: its public fork protocol exposes turn boundaries only. For an injected
edit, CCM resolves the containing native turn, forks through the completed turn
immediately before it, and records the ordinary user input(s) that preceded the
selected injection in that turn as a hidden replay prefix. The edited text is
shown as the branch's user message, while the first native prompt contains the
replay prefix followed by the edited steer.

The existing in-session branch model remains unchanged: the original and edited
versions are separate hidden Tasks selected through the left/right controls,
and reopening the visible session restores the last selected branch.

Every new Codex injection persists the exact turn id returned by the successful
race-fenced `turn/steer` call. Historical injections do not have that metadata.
For those rows, the first subsequent event that maps to the same native thread,
before the next ordinary user message, is the authoritative containing turn.
This is important for Goal sessions: later automatic Goal turns may occur in
the same ordinary-message segment, but they do not make the earlier steer
ambiguous. Only earlier user inputs mapped to the same containing turn are
replayed.

## Safety rules

- Only human `source=inject` rows become editable; Monitor and sub-agent rows do
  not.
- An injected row is accepted only when its persisted steer id or its first
  following native event identifies a turn with a completed predecessor.
- Historical rows with no safe following native event return a conflict
  instead of guessing from message ordinal or later Goal turns.
- Replay metadata is one-shot and removed after the first edited message is
  durably admitted.
