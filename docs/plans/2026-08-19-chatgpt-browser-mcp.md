# ChatGPT Browser MCP Prototype Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let an isolated Codex CLI session on the CCM server operate one persistently logged-in ChatGPT web profile through a narrow STDIO MCP server.

**Architecture:** A reusable Python Playwright service owns one locked persistent Chrome profile. A FastMCP adapter exposes only semantic ChatGPT operations, while a CLI wrapper provides headed login and smoke-test commands using the same service.

**Tech Stack:** Python 3.11+, Playwright async API, FastMCP, pytest, TigerVNC/noVNC, Codex CLI MCP configuration.

---

### Task 1: Define the browser service contract

**Files:**
- Create: `backend/services/chatgpt_browser.py`
- Create: `backend/tests/test_chatgpt_browser.py`

**Steps:**
1. Write failing tests for ChatGPT URL validation, private profile creation,
   symlink rejection, lock contention, message bounds, and response bounds.
2. Run `pytest backend/tests/test_chatgpt_browser.py -q` and confirm failure.
3. Implement configuration, validation, private directory creation, and the
   cross-process profile lock.
4. Add a Playwright-backed session with `start`, `close`, `status`,
   `open_conversation`, `send_message`, and `wait_for_reply` methods.
5. Mock the browser boundary and test authenticated, logged-out, timeout, and
   selector-drift paths.
6. Run the focused tests and commit the service.

### Task 2: Add the narrow MCP adapter and CLI

**Files:**
- Create: `backend/mcp/ccm_chatgpt_browser_server.py`
- Create: `scripts/chatgpt_browser_poc.py`
- Modify: `backend/tests/test_mcp_config.py`
- Create: `backend/tests/test_chatgpt_browser_mcp.py`

**Steps:**
1. Write tests asserting the exact registered MCP tool set and bounded JSON
   error contract.
2. Implement `chatgpt_status`, `chatgpt_open_conversation`,
   `chatgpt_send_message`, `chatgpt_wait_for_reply`, and
   `chatgpt_conversation_url`.
3. Add CLI commands `login`, `status`, `send`, and `wait`; credentials must
   never be accepted as arguments.
4. Add a builder for an isolated ChatGPT Browser MCP spec without enabling it
   in ordinary CCM tasks.
5. Run the MCP and config tests and commit.

### Task 3: Verify the local implementation

**Files:**
- Modify as required by test failures only.

**Steps:**
1. Run the focused backend tests.
2. Run Ruff/compile checks used by this repository for the new Python files.
3. Run the broader MCP config regression suite.
4. Review the diff for credentials, absolute development paths, and accidental
   production enablement.

### Task 4: Prepare an isolated CCM server runtime

**Files:**
- Server-only test checkout outside the production checkout.
- Server-only private runtime directory under `~/.local/share/ccm/`.

**Steps:**
1. Push or copy the exact branch commit into a separate server checkout.
2. Verify the production checkout HEAD and service remain unchanged.
3. Reuse the server virtual environment only when its dependencies match;
   otherwise create a small isolated virtual environment without database
   setup or update scripts.
4. Start a localhost-only TigerVNC display and noVNC proxy on unused ports.
5. Start the headed login command and provide the SSH tunnel URL to the user.

### Task 5: Perform real login and Codex MCP verification

**Steps:**
1. Wait for the user to complete login and explicitly report readiness.
2. Confirm `status` reports authenticated without exposing profile data.
3. Close and restart the browser command; confirm authentication persists.
4. Start an isolated Codex CLI invocation with only the prototype MCP added.
5. Send a benign nonce prompt and verify the expected ChatGPT response.
6. Record command output, conversation URL, branch commit, and remaining risks.
7. Stop test processes; preserve the private profile unless the user requests
   deletion. Do not deploy or enable the feature in production CCM.
