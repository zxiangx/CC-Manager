# Apex GLM Codex Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run every GLM model returned by the new Apex key through CCM's native Codex harness, defaulting to `glm-5.3`.

**Architecture:** Extend Apex model discovery to classify `glm-*` as Codex models. Add a model-gated Responses-to-Anthropic adapter behind the existing loopback Codex proxy, preserving the native Codex app-server and all non-GLM routes.

**Tech Stack:** Python 3.11, asyncio, httpx, Codex app-server 0.145.0, Anthropic Messages API, pytest, React/TypeScript configuration consumers.

---

### Task 1: Discover and advertise GLM models

**Files:**
- Modify: `backend/services/cloudrouter_accounts.py`
- Modify: `backend/config.py`
- Modify: `backend/services/codex_models.py`
- Test: `backend/tests/test_cloudrouter_accounts.py`
- Test: `backend/tests/test_codex_models.py`

**Steps:**
1. Add failing tests that Apex `glm-*` ids are retained as Codex models and Standard-only capabilities.
2. Run the focused tests and confirm the new assertions fail.
3. Add provider-aware GLM classification, all nine UI model options, `glm-5.3` default, effort/context metadata, and Standard-only tiers.
4. Run the focused tests and confirm they pass.

### Task 2: Translate Responses requests into Apex Messages

**Files:**
- Create: `backend/services/codex_glm_adapter.py`
- Test: `backend/tests/test_codex_glm_adapter.py`

**Steps:**
1. Add failing tests for instructions/messages, function/custom tools, previous tool calls, and tool results.
2. Implement bounded JSON validation and deterministic conversion into Anthropic Messages payloads.
3. Add failing tests for text/tool-use responses and Responses SSE terminal ordering.
4. Implement response conversion and safe upstream error conversion.
5. Run the adapter test module.

### Task 3: Gate the adapter inside the Codex loopback proxy

**Files:**
- Modify: `backend/services/codex_tier_proxy.py`
- Modify: `backend/services/instance_manager.py`
- Test: `backend/tests/test_codex_tier_proxy.py`

**Steps:**
1. Add failing tests proving only GLM models on a registered Apex account use `/messages` with `x-api-key`.
2. Extend `CodexTierProxyRoute` with an immutable GLM model set sourced from the account metadata.
3. Invoke the adapter for matching Standard requests and leave every other request byte-for-byte on the existing path.
4. Run proxy and instance-manager focused tests.

### Task 4: End-to-end Codex verification

**Files:**
- Test: `backend/tests/test_codex_glm_integration.py`

**Steps:**
1. Start a mock Apex Messages service and the real Codex app-server.
2. Verify a `glm-5.3` turn produces assistant text.
3. Verify a GLM tool request is executed by Codex and its result is returned on the next model request.
4. Run the relevant backend suite and frontend configuration tests.

### Task 5: Commit, deploy, and validate production

**Files:**
- No secret-bearing files are committed.

**Steps:**
1. Commit the implementation and tests.
2. Synchronize the exact commit to the CCM server repository and verify the remote-server `HEAD`.
3. Deploy the synchronized commit without treating repository synchronization as a reason to stop active tasks.
4. Add the supplied GLM key as a separate Apex account through the account store/API.
5. Verify all nine GLM models are projected into the Codex pool, `glm-5.3` is the default, and a real Codex task completes a tool round-trip.
