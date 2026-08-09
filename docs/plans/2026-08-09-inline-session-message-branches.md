# Inline Session Message Branches Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users edit an old message in place and continue on a preserved branch without leaving the visible CCM session.

**Architecture:** Keep native Codex thread forks and hidden Tasks as execution details. Add a canonical Task-to-active-branch pointer, render the selected hidden Task inside the canonical session shell, and persist branch selection on the server so reopening the session restores the last viewed branch.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, React, TypeScript, Vitest, pytest.

---

### Task 1: Persist the active internal branch

**Files:**
- Modify: `backend/models/task.py`
- Create: `alembic/versions/8c1f4a7d2e90_add_active_message_branch_task.py`
- Modify: `backend/api/chat.py`
- Test: `backend/tests/test_api_chat_plan.py`

**Steps:**
1. Add failing API tests for selecting a branch and restoring it through the canonical Task.
2. Add nullable self-referencing root/active branch fields to `Task` and an Alembic migration.
3. Set the branch root on internal fork Tasks and expose GET/PUT branch-session endpoints.
4. Validate access and reject selecting Tasks outside the canonical branch family.
5. Run the focused backend tests.

### Task 2: Keep the canonical session open while branches change

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/Chat/ChatView.tsx`
- Modify: `frontend/src/pages/TasksPage.tsx`
- Test: `frontend/src/components/Chat/ChatView.test.tsx`

**Steps:**
1. Add API types and methods for restoring/selecting the active runtime Task.
2. Wrap the existing chat runtime in a canonical-session component.
3. Keep URL, sidebar selection, title, and tag bound to the canonical Task.
4. Bind history, WebSocket, sending, stopping, Goal, and Monitor operations to the selected runtime Task.
5. Persist each branch switch before rendering it.

### Task 3: Replace the fork navigation with inline editing

**Files:**
- Modify: `frontend/src/components/Chat/ChatView.tsx`
- Test: `frontend/src/components/Chat/ChatView.test.tsx`

**Steps:**
1. Add a failing component test for converting a user bubble into a prefilled editor.
2. Implement save/cancel controls for initial and follow-up messages.
3. On save, create the internal native branch, send the edited text, persist it as selected, and render the new branch without navigation.
4. Preserve original attachments and display errors without losing the draft.
5. Verify previous/next controls switch complete contexts within the same session.

### Task 4: Regression and production verification

**Files:**
- Modify: `PROGRESS.md`

**Steps:**
1. Run focused backend and frontend tests.
2. Run the frontend production build and relevant backend suite.
3. Inspect the diff for accidental ordinary-fork or sidebar behavior changes.
4. Record the completed behavior and verification in `PROGRESS.md`.
