# Native Goal Pause/Resume Control

## Intent

Keep the Codex-native Goal as the only source of truth while making `paused`
a first-class retained state. Pausing must preserve the objective, token/time
accounting, and progress; it must prevent autonomous continuation. Clearing is
the only destructive operation.

## Control model

- The user Goal panel can pause, resume, or permanently delete the Goal.
- Codex continues to create Goals with its native `create_goal` tool.
- A task-scoped, narrow CCM MCP surface gives the main Codex Agent
  `ccm_pause_goal` and `ccm_resume_goal`. It never exposes deletion to the
  Agent.
- User pause interrupts the current Goal generation after first persisting
  `paused`. Agent pause persists `paused` but lets the current turn finish so
  its tool result and final explanation are not cut off.
- Resume is admitted through the existing per-Task dispatcher lifecycle. The
  endpoint enqueues one invisible control continuation without first mutating
  the retained state. The normal app-server path creates the CCM owner before
  `thread/goal/set active`, observes the exact `turn/started`, and steers a
  bounded resume instruction into that turn.
- Ordinary chat never resumes a retained paused/blocked/limited/completed
  Goal. Only the explicit Goal-control path can enable it, so a deliberate
  pause cannot be undone by asking the Agent an unrelated question.

## Safety and races

- Every operation resolves the Task's persisted Codex account and thread; it
  never scans or guesses among rollout copies.
- Goal state mutations are serialized by the registry's per-thread operation
  reservation. Manual pause also clears the internal descendant-gate resume
  flag under the same context lock, so a Goal paused by the user or Agent is
  not accidentally reactivated when a child Agent later becomes idle.
- Resume returns accepted while the control continuation is waiting for an
  already-running turn. The UI polls the authoritative native Goal until it is
  active; no synthetic user bubble is persisted.
- Delete retains the existing stop, clear, and read-after-clear proof.
- Worker Tasks proxy the same state-control endpoint to the authoritative
  Worker.

## Verification

- Protocol tests cover active-turn pause, authoritative status verification,
  descendant-gate cancellation, and retained Goal resume admission.
- API tests cover user pause, Agent-finish-current-turn pause, and invisible
  resume enqueue; protocol tests cover idempotent pause and missing Goals.
- MCP tests prove the Agent receives only pause/resume (not delete) even when
  the broader Codex main-MCP feature is disabled.
- UI tests cover state-dependent Pause/Resume buttons, loading/error states,
  and the existing two-click destructive delete confirmation.
