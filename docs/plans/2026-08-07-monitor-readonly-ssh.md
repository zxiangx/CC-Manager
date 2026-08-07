# Monitor Read-only SSH Proxy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give CCM Monitor a secure, structured read-only SSH capability for configured hosts and stop permanently incapable monitors instead of reporting false success forever.

**Architecture:** Keep the agent sandbox unchanged. Add one Monitor MCP tool that calls an authenticated, generation-fenced loopback endpoint; the backend validates a configured profile, builds a fixed read-only command, and executes it through the existing Paramiko transport with strict host-key checking.

**Tech Stack:** Python 3, FastAPI, Pydantic Settings, SQLAlchemy async, FastMCP, Paramiko, pytest.

---

### Task 1: Harden the reusable SSH transport

**Files:**
- Modify: `backend/services/ssh_executor.py`
- Test: `backend/tests/test_ssh_executor.py`

**Steps:**
1. Add failing tests for custom ports, rejecting unknown host keys, and bounded output.
2. Run the focused tests and confirm they fail.
3. Add backwards-compatible `port`, `strict_host_key_checking`, and `max_output_bytes` parameters.
4. Run the focused tests and confirm they pass.

### Task 2: Implement structured remote reads

**Files:**
- Modify: `backend/config.py`
- Create: `backend/services/monitor_remote_read.py`
- Create: `backend/tests/test_monitor_remote_read.py`

**Steps:**
1. Add failing tests for profile parsing, operation templates, injection rejection, lexical traversal and remote realpath guards.
2. Add `monitor_ssh_profiles` configuration and strict profile parsing.
3. Implement fixed templates for connection/process/GPU/Slurm/log/stat/tmux reads.
4. Enforce timeout, output cap and stable transient/permanent error classification.
5. Run the service tests.

### Task 3: Expose the capability to exact Monitor turns

**Files:**
- Modify: `backend/schemas/monitor_session.py`
- Modify: `backend/api/monitor.py`
- Modify: `backend/mcp/ccm_monitor_agent_server.py`
- Modify: `backend/services/mcp_config.py`
- Modify: `backend/services/dispatcher.py`
- Test: `backend/tests/test_api_monitor.py`
- Test: `backend/tests/test_mcp_config.py`
- Test: `backend/tests/test_monitor_dispatcher.py`

**Steps:**
1. Add failing endpoint, MCP tool snapshot and prompt tests.
2. Add a generation-fenced internal remote-read endpoint.
3. Add a generation-fenced terminal capability-failure endpoint.
4. Add `read_remote_status` to the Monitor MCP server and auto-report permanent failures.
5. Update the prompt to prefer the proxy for remote checks and forbid direct SSH.
6. Run all Monitor tests.

### Task 4: Configure and deploy `yc_h100`

**Files:**
- Modify on server: deployment environment only; never commit a credential path or secret value.

**Steps:**
1. Validate the server-side SSH profile, key permissions and `[host]:port` known_hosts entry.
2. Configure `CCM_MONITOR_SSH_PROFILES` with the allowed remote roots.
3. Deploy the exact local branch without pulling upstream.
4. Restart CCM and verify public health.
5. Call the internal path through a real Monitor turn and confirm connection, Slurm and GPU reads.
6. Confirm a missing profile terminates once instead of scheduling repeated false-success checks.
