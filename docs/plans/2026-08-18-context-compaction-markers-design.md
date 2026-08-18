# Context Compaction Markers Design

## Objective

Every context compaction must leave a prominent, durable divider in the Task
chat. Users must not need an Agent-authored sentinel such as `imcodex_1` to
infer that context was compacted.

## Event Contract

Compaction markers remain ordinary persisted `system_event` rows so existing
history, pagination, Worker relay, and shared-chat storage continue to work.
Their content starts with the stable machine-readable prefix
`[Context compacted · <kind>]`. The UI recognizes only that prefix and renders
the row as a high-contrast violet divider rather than a generic gray system
message.

Kinds are user-facing and describe the source:

- `Automatic`: Codex emitted a native `contextCompaction` completion.
- `Manual`: CCM accepted the user's native compact request.
- `CCM automatic`: CCM summarized an over-limit context into a replacement
  session.
- `Safe recovery`: CCM summarized a quarantined or missing session before
  launching a replacement.

## Data Flow

Codex app-server currently classifies `contextCompaction` as passive metadata
and drops it. It will instead forward a synthetic completed event. The Codex
line parser converts that event into the stable system marker, after which the
normal InstanceManager persistence and WebSocket broadcast path is reused.

The manual compact API persists and broadcasts its marker only after Codex
acknowledges the asynchronous compact request. Existing CCM summary paths use
the same prefix for their already-persisted notices. No schema migration is
required.

## Verification

- Native automatic compaction produces one persisted/broadcast marker.
- A rejected manual compaction produces no marker; an accepted request does.
- Historical and live markers render with the same prominent divider.
- Ordinary system events keep their existing presentation.
