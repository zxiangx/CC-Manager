# Native Goal recovery and restricted agent control

## Problem

Codex can persist a native Goal as `blocked` when a Goal turn ends because of
a transient transport failure such as `stream disconnected before completion`.
That state does not mean the objective is semantically blocked, but CCM
currently retries the failed prompt as an ordinary turn. The ordinary turn can
continue doing useful work while the durable Goal remains detached and
`blocked`. A later CCM-created replacement thread (safe recovery or context
compaction) can also lose the Goal because native Goals are keyed by Codex
thread id rather than CCM Task id.

CCM already exposes task-scoped agent tools for pausing and resuming a retained
Goal. It does not expose the app-server's supported `objective` update field,
and it intentionally does not expose Goal deletion to the agent.

## Design

Treat a transient provider failure as an interruption, not a semantic blocker.
When the failed Codex adapter was following a native Goal, CCM records that
fact on the exact process generation. Before a same-thread transient retry it
normalizes Codex's automatic `blocked` state to `paused`; the retry then uses
the existing explicit Goal-resume path, which establishes the CCM owner before
setting the Goal active and steering the pending input. If the retry budget is
exhausted, the Goal remains paused and recoverable instead of falsely blocked.
Ordinary transient turns that merely coexist with an intentionally paused or
blocked Goal do not reactivate it.

Add a restricted `ccm_update_goal(objective)` MCP tool. It calls the existing
Task-authorized native Goal endpoint, which uses `thread/goal/set` with the
`objective` field and verifies the returned Goal. The endpoint continues to
accept only `active` and `paused` status control. The agent tool inventory
contains create (Codex native), pause, resume, and objective update, but never
contains `thread/goal/clear` or CCM's DELETE endpoint. User-facing Goal deletion
remains available through the existing panel.

For CCM-created replacement sessions, snapshot the retained Goal into bounded
Task metadata before clearing `Task.session_id`. The snapshot contains only
the objective, intended active/paused state, and remaining token budget; it
does not copy native thread history or internal usage counters. A fresh Codex
thread is seeded with the Goal in `paused` state before model input. Active
handoffs then use the same owner-first resume-and-steer path; paused handoffs
stay paused while the ordinary queued message runs. Clear the pending handoff
only after the replacement thread has accepted the native Goal.

## Error handling and tests

All Goal RPCs remain fail-closed. A failed objective update returns 409 and
does not report success. A failed handoff leaves the Task metadata intact for
retry. A transient retry that cannot inspect or normalize the Goal logs the
failure and does not claim the Goal was repaired.

Regression tests cover: Goal-following process identity, transient blocked to
paused normalization plus explicit resume, retry exhaustion leaving the Goal
paused, objective update without status mutation, absence of a delete agent
tool, and active/paused Goal restoration on a fresh thread. Existing retained
Goal, request-block recovery, compaction, backend, and frontend type tests must
remain green.
