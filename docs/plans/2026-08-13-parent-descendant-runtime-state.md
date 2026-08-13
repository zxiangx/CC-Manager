# Parent/Descendant Runtime State Implementation Plan

**Goal:** Distinguish an active root Codex turn from descendant-only work, and let a user message start a new root turn while descendants remain active.

**Architecture:** Codex app-server remains the source of truth for native root and descendant lifecycle. The backend exposes that state through the existing inject-capabilities endpoint. When only descendants are active, a dedicated parent-follow-up path starts a new `turn/start` on the retained root thread and reuses the existing CCM process consumer. The chat composer chooses steer, parent follow-up, normal send, or queue from the authoritative state and renders a separate descendant-only marker.

**Tech Stack:** FastAPI, async Codex app-server JSON-RPC, React/TypeScript, pytest, Vitest.

---

### Task 1: Expose authoritative execution state

**Files:**
- Modify: `backend/services/codex_app_server.py`
- Modify: `backend/services/instance_manager.py`
- Modify: `backend/api/chat.py`
- Test: `backend/tests/test_codex_app_server.py`
- Test: `backend/tests/test_api_chat_plan.py`

Add a root/descendant execution snapshot based on app-server lifecycle observations, not the coarse Task status. Return root-turn activity, descendant activity/count, and parent-follow-up support from inject capabilities.

### Task 2: Start a root follow-up inside a retained descendant lineage

**Files:**
- Modify: `backend/services/codex_app_server.py`
- Modify: `backend/services/instance_manager.py`
- Modify: `backend/api/chat.py`
- Test: `backend/tests/test_codex_app_server.py`
- Test: `backend/tests/test_api_chat_plan.py`

Persist the safe reusable `turn/start` configuration in the live context. Add a serialized parent-follow-up operation that is admitted only after the previous root turn completed and descendants remain active. Persist and broadcast the user message only after the native turn id is confirmed.

### Task 3: Route and label the composer correctly

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/Chat/ChatView.tsx`
- Test: `frontend/src/components/Chat/ChatView.test.tsx`

Refresh execution capabilities during active tasks and immediately before send. Steer only while the root turn is active. In descendant-only state, start a parent follow-up and display a distinct child-Agent-running marker, copy, icon, and button treatment.

### Task 4: Regression verification

Run focused backend and frontend tests, static/type checks for touched surfaces, and inspect the final diff for unrelated changes.
