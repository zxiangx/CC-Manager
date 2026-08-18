# Request-Blocked Automatic Recovery Design

## Objective

When a chat-initiated Codex turn terminates with `Request blocked`, CCM should
immediately continue through its existing safe-session recovery path instead
of waiting for another user message. The replacement turn receives this
harness-generated instruction as its current message:

> The content returned by your previous request caused a Request blocked
> error. Please use a different approach and continue.

## Design

The terminal consumer remains the authority for detecting the structured
provider failure. It first commits the existing quarantine marker and releases
the exact Task/Instance generation. Only after process and registry cleanup is
complete does it enqueue a normal serialized Task message with a dedicated
`request_blocked_recovery` marker.

The Dispatcher does not add a second recovery implementation. Its existing
quarantine branch summarizes bounded chat history, refuses to resume the
poisoned native thread, clears the active quarantine marker, and launches a new
Codex thread. The English harness instruction is the new turn's highest
priority current message.

## Loop Protection

The dedicated marker is carried from `QueuedMessage` into InstanceManager's
exact launch parameters. If the automatic recovery turn is itself blocked,
the terminal consumer quarantines that replacement thread but does not enqueue
another automatic recovery. A later real user message starts a new one-shot
recovery opportunity. This prevents an unattended Request-blocked loop while
still recovering every user-initiated turn once.

## Verification

- A first blocked Codex chat enqueues the exact English recovery instruction.
- The queued recovery launches with no poisoned `resume_session_id`.
- A blocked turn already marked as automatic recovery does not enqueue again.
- Non-Codex and non-`Request blocked` failures remain unchanged.
