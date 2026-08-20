# Apex GLM Streaming Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Stream Apex GLM text and tool events through CCM's Codex Responses compatibility route as they arrive.

**Architecture:** Add a bounded stateful Anthropic Messages SSE-to-Responses SSE adapter, then replace the GLM proxy route's full-body buffering with incremental parsing and forwarding. Keep non-2xx errors buffered and preserve all existing model, tier, credential, and tool gates.

**Tech Stack:** Python 3.11+, asyncio, httpx, pytest, raw HTTP/SSE loopback proxy.

---

### Task 1: Specify streaming adapter behavior

**Files:**
- Modify: `backend/tests/test_codex_glm_adapter.py`
- Modify: `backend/tests/test_codex_tier_proxy.py`

1. Add a unit test that feeds `message_start`, text block start/deltas/stop, `message_delta`, and `message_stop` separately.
2. Assert the adapter emits a text delta before completion and builds a valid final Responses object.
3. Add function and custom tool stream tests, including fragmented JSON.
4. Add malformed ordering and premature EOF tests.
5. Run the focused tests and verify they fail because the stream adapter does not exist.

### Task 2: Implement bounded event conversion

**Files:**
- Modify: `backend/services/codex_glm_adapter.py`

1. Add an `AnthropicMessagesStreamAdapter` with response identity, sequence number, block state, output items, and usage state.
2. Map message and content-block lifecycle events to the existing Responses event shapes.
3. Validate tool names and completed JSON; bound accumulated text and tool input.
4. Add an EOF check so incomplete streams fail closed.
5. Run `backend/tests/test_codex_glm_adapter.py` and verify it passes.

### Task 3: Stream through the loopback proxy

**Files:**
- Modify: `backend/services/codex_tier_proxy.py`
- Modify: `backend/tests/test_codex_tier_proxy.py`

1. Change the translated Apex request to `stream: true` with SSE accept headers.
2. Preserve bounded buffering for non-2xx errors.
3. For successful SSE responses, split complete records incrementally, convert each event, write each converted record, and drain the downstream writer.
4. Validate content type, content encoding, prelude size, event size, and clean completion.
5. Use a gated mock stream to assert the downstream first delta arrives before upstream completion is released.
6. Run proxy and integration-focused tests.

### Task 4: Regression, commit, deploy, and verify

**Files:**
- Modify only if failures reveal a scoped compatibility defect.

1. Run the GLM adapter, tier proxy, instance manager, account, and Codex pool test subsets.
2. Review the diff and confirm no credential material or unrelated changes are present.
3. Commit the implementation and plans.
4. Synchronize that exact commit to `/home/ubuntu/.claude-code-manager/claude-code-manager` without treating code sync as a session pause.
5. Deploy using the repository's established deployment procedure.
6. Verify server HEAD and running version match the target commit, then run an online GLM turn or equivalent streaming probe and confirm first output arrives before completion.
