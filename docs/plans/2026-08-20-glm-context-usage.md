# GLM Context Usage Correction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Persist Apex GLM input-token usage and GLM-specific context windows accurately.

**Architecture:** Update the streaming protocol adapter from terminal Apex usage fields, then normalize GLM context windows at CCM's persistence boundary. Leave frontend calculations and non-GLM Codex behavior unchanged.

**Tech Stack:** Python, asyncio, pytest, SQLAlchemy.

---

### Task 1: Correct terminal Apex usage

**Files:**
- Modify: `backend/tests/test_codex_glm_adapter.py`
- Modify: `backend/services/codex_glm_adapter.py`

1. Change the streaming test to model Apex's zero start usage and nonzero terminal input/cache/output usage.
2. Run the test and confirm the final Responses usage is wrong.
3. Update `_message_delta` so each present usage field replaces its stored value.
4. Run the adapter tests and confirm they pass.

### Task 2: Normalize GLM context windows

**Files:**
- Modify: `backend/tests/test_service_instance_manager.py`
- Modify: `backend/services/instance_manager.py`

1. Add a persistence test where GLM-5.3 arrives with a generic 258,400 window.
2. Assert the stored and broadcast window is 204,800.
3. Add provider/model-aware normalization before context usage is persisted.
4. Run the focused instance-manager tests.

### Task 3: Verify, commit, and deploy

**Files:**
- Modify only if scoped regressions expose a defect.

1. Run adapter, tier proxy, model, message-pipeline, and focused instance-manager tests.
2. Run syntax and diff checks.
3. Commit all source, test, and design changes.
4. Synchronize the exact commit to the CCM server and verify server HEAD.
5. Deploy the local server version and verify health/running commit.
6. Execute a sanitized live GLM probe and confirm nonzero input usage plus a 204,800 persisted/effective window.
