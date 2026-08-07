# Unified live-message composer

## Goal

Remove the manual injection-mode switch. The ordinary composer should send a
message into the currently running local Agent turn whenever the active
transport can acknowledge live injection.

## Routing

- A running local Codex app-server turn uses `turn/steer` through the existing
  `/inject` endpoint.
- A running local Claude PTY turn uses `session.inject` through the same
  endpoint.
- An idle Task uses the existing normal follow-up endpoint.
- Worker, shared, and transports without live-injection support keep the
  existing next-turn queue behavior.

The frontend chooses among these already-existing, fail-closed paths. It does
not add a second backend injection implementation or silently fall back after
an uncertain injection response, which could execute the same message twice.

## Interaction and failure behavior

While a supported turn is running, the composer explains that Send will add to
the current turn and uses the existing teal live-message styling. There is no
mode toggle. Text, files, paste, quick phrases, and Ctrl/Cmd+Enter all use the
same routing decision. Secrets remain disabled for a live injection because
they are a next-turn feature.

The composer stays frozen while injection is in flight. It clears only after
the server acknowledges the message and, for attachments, the exact attachment
count. Any ambiguous or failed response preserves the text and files for a
deliberate retry.

## Verification

The ChatView suite verifies automatic Codex steering, exact attachment
metadata, capability negotiation, failure preservation, in-flight freezing,
failed upload handling, and Worker queue fallback. TypeScript compilation must
also pass.
