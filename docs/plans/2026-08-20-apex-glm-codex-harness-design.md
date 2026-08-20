# Apex GLM through the Codex harness

## Architecture

CCM will continue launching the native Codex app-server and preserving its task, rollout, tool, compaction, and session semantics. The existing loopback `CodexActualTierProxy` remains the only network route exposed to the app-server. For an Apex API account and a model whose id starts with `glm-`, the proxy will translate the incoming OpenAI Responses request into one non-streaming Anthropic Messages request to Apex `/v1/messages`, then translate the returned text or tool-use blocks into a valid Responses SSE sequence. Non-GLM Apex models continue through the current transparent `/responses` path unchanged.

The adapter is model-gated and account-gated. It never accepts arbitrary upstream URLs, never logs or persists credentials, and converts the Codex bearer credential to `x-api-key` only for the fixed Apex endpoint. Standard tier is supported; Fast remains unavailable because the GLM catalog does not advertise it. All nine models discovered from the supplied Apex key are exposed as Codex models, with `glm-5.3` as the CCM default.

## Data flow and tool compatibility

Responses `instructions` and message items become Anthropic system/messages content. Codex function tools map directly to Anthropic tools. Codex custom tools such as `apply_patch` and shell execution are represented with a single string input field so GLM can request them; returned `tool_use` blocks are converted back to the original Responses function/custom call type. Prior function/custom calls and their outputs are reconstructed as assistant `tool_use` and user `tool_result` blocks on subsequent turns.

The first implementation deliberately buffers one upstream GLM response before emitting SSE. This sacrifices token-by-token text streaming but makes terminal ordering, error handling, and tool-call conversion deterministic. CCM still displays all normal Codex tool progress after each model response. Apex authentication, quota, rate-limit, and model errors are returned through the existing pool rotation paths.

## Verification

Unit tests cover model discovery, request conversion, text response conversion, function/custom tool conversion, credential handling, and preservation of non-GLM routes. An integration test runs the real Codex app-server against a mock Apex Messages endpoint and proves a model turn plus a local tool round-trip. Production verification adds the supplied key as a separate Apex account, confirms all nine models appear, launches a small `glm-5.3` Codex task, and verifies that the task invokes a tool and completes.
