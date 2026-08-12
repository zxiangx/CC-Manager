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

## Safety rules

- Only human `source=inject` rows become editable; Monitor and sub-agent rows do
  not.
- An injected row is accepted only when it maps to exactly one native turn and
  that turn has a completed predecessor.
- Ambiguous history returns a conflict instead of guessing.
- Replay metadata is one-shot and removed after the first edited message is
  durably admitted.

