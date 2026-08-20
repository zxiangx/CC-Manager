# Apex GLM True Streaming Design

## Goal

Make Apex-hosted GLM turns stream through the existing Codex harness instead of waiting for the complete model response. Preserve the current model gate, tool translation, bounded parsing, and fail-closed behavior.

## Chosen approach

CCM will request the Apex Anthropic-compatible `/v1/messages` endpoint with `stream: true`. A stateful adapter will translate each Anthropic Messages SSE event into the corresponding OpenAI Responses SSE event. The loopback tier proxy will forward each translated record immediately and drain the socket, so Codex receives text deltas as Apex generates them.

This is preferred over two alternatives. Splitting a completed response into artificial chunks would improve animation only, not latency. Routing GLM outside the Codex harness would lose native thread, tool, and rollout behavior. Incremental protocol translation keeps the established harness intact and reduces time to first visible output.

## Event and state mapping

- `message_start` creates `response.created` and `response.in_progress` and captures response identity and input-token usage.
- Text `content_block_start` creates the Responses output item and content part.
- `text_delta` becomes `response.output_text.delta` immediately.
- Text `content_block_stop` emits the matching done events and stores the completed item.
- Function-tool JSON deltas become `response.function_call_arguments.delta`; the completed JSON is validated at block stop.
- Custom-tool input remains buffered until the wrapper JSON object is complete, then emits its safe unwrapped input. This avoids corrupting escaped JSON strings while preserving text streaming.
- `message_delta` updates output-token usage and stop state.
- `message_stop` emits `response.completed` with the accumulated output and usage.
- Ping and ignored thinking events produce no downstream records. Malformed ordering, unknown tools, oversized buffers, upstream error events, and premature EOF fail closed.

## Proxy behavior and verification

The proxy validates a successful identity-encoded SSE response before committing downstream headers. Once `message_start` is translated, it sends SSE headers and flushes every translated record. Non-2xx Apex responses remain ordinary bounded HTTP errors. Tests use a gated asynchronous upstream stream to prove the first text delta reaches the Codex-facing client before the upstream completion event is released. Existing complete-response conversion remains available for focused compatibility tests, while the live route uses the stateful stream adapter.
