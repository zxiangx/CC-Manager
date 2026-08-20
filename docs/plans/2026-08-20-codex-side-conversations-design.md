# Codex Side Conversations Design

## Goal

Make long CCM conversations readable without losing execution evidence, and let a user investigate any completed Codex answer without changing the main session.

## Design

Assistant bubbles expose a Side action only when the persisted row has a native turn id and is not commentary. The backend validates the row, reads native thread history, requires the containing turn to be terminal, and calls Codex `thread/fork` with that exact turn. The fork is a normal Task for reuse of chat, streaming, routing, and deletion infrastructure, but carries `ccm_side_branch`, parent/anchor metadata, and `archived=true`; it is not auto-shared or shown in the normal task list.

The parent ChatView stores the active Side Task id per parent in localStorage. It restores the floating window after refresh, supports minimize, and permanently deletes only on the explicit delete control. The embedded ChatView runs in side mode so it does not create recursive side docks or take over document scrolling.

Completed process output is grouped at render time, without rewriting logs. Commentary, thinking, tool calls/results, and compaction markers become one expandable Activity row. While the Task is active, the same items remain expanded. User messages, including live injections, are never placed inside the collapsed group. Structured Plan cards stay visible.

Text selection is scoped to an assistant bubble. The Ask action converts the selection to a Markdown block quote in the existing composer and focuses it; sending remains an explicit user action.

## Verification

Backend tests cover completed/running assistant turn resolution. ChatView tests cover Side fork arguments and persistence, folding behavior, current-turn visibility, compaction markers, and selection quoting. Production verification must compare the server disk commit and running commit after deployment.

## Implementation Plan

1. Extend `ForkAnchor` and `/api/tasks/{id}/fork` with `assistant_message` and `side_branch`; resolve the selected row through `_ForkTurnIndex`, reject non-terminal turns, and persist hidden Side metadata.
2. Expose Codex message phase in chat history so the client can distinguish commentary from final answers.
3. Add a response-level Side control, localStorage restoration, and an embedded minimizable/deletable ChatView.
4. Group terminal turn activity in the renderer while leaving active output, injections, final answers, and Plan cards outside the group.
5. Add bubble-scoped text selection quoting.
6. Run focused backend/frontend tests, type/build checks, commit, sync the exact commit, deploy, and verify the running commit.
