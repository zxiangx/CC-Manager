# ChatGPT Browser MCP Prototype Design

## Goal

Prove that a Codex CLI session launched on the CCM server can use a task-scoped
MCP server to operate a persistently logged-in ChatGPT web account. The proof
must not depend on the proprietary desktop in-app Browser, expose browser
credentials to the model, modify the production database, or restart the
production CCM service.

## Scope

The prototype runs from a separate server checkout and owns one dedicated
Chromium profile. It supports status inspection, opening a conversation,
sending one text message, waiting for a complete reply, and returning the
current conversation URL. A headed login command uses the same profile under a
private VNC display so the user can complete passwords, CAPTCHA, passkeys, or
two-factor authentication personally.

The prototype is deliberately single-account and single-controller. It does
not provide arbitrary cookie access, generic JavaScript execution, private
ChatGPT HTTP endpoints, file uploads, multi-user account sharing, or automatic
production Task injection.

## Architecture

`ChatGPTBrowserSession` is the only component that owns Playwright and the
persistent browser profile. It acquires a filesystem lock before starting
Chromium, launches the system Chrome channel with a fixed private user-data
directory, and exposes semantic operations. Authentication is determined from
visible ChatGPT page state rather than from cookies or storage.

`ccm_chatgpt_browser_server` is a thin STDIO FastMCP adapter. It translates MCP
tool calls into the session operations and returns bounded JSON. The MCP
process never returns browser storage, credentials, raw HTML, or unbounded page
content. A separate CLI wrapper reuses the same service for headed login and
manual smoke tests.

For the server proof, an isolated TigerVNC display and noVNC proxy bind only to
localhost. The user reaches noVNC through an SSH tunnel. The production CCM
checkout, database, systemd service, and port 8000 are not touched.

## Data Flow

1. The login command starts Chrome on the private display with the persistent
   profile and opens `https://chatgpt.com/`.
2. If authentication is required, it prints a machine-readable
   `login_required` state and remains alive while the user signs in through
   noVNC.
3. Once the authenticated chat composer is visible, the command closes Chrome;
   the profile remains on disk.
4. Codex CLI starts the STDIO MCP server. The server reopens the same profile,
   performs semantic DOM operations, and serializes access with the profile
   lock.
5. `send_message` returns only after the prompt appears in the conversation.
   `wait_for_reply` waits for generation to settle and returns the latest
   assistant reply with a strict size bound.

## Safety and Failure Handling

- Profile and lock directories must be absolute, private, non-symlink paths.
- Only `https://chatgpt.com/` conversation URLs are accepted.
- Message and response sizes are bounded.
- One profile can have only one live browser owner.
- Login challenges return `login_required`; credentials are never accepted by
  MCP tools.
- Selector drift, logout, timeout, browser crashes, and concurrent ownership
  return explicit structured errors.
- The real smoke test sends only a user-approved benign nonce prompt.

## Verification

Unit tests cover URL validation, private profile preparation, locking, bounded
outputs, login-state classification, and MCP tool registration. Server checks
prove Chrome, Xvfb/VNC, noVNC, and Playwright availability. The final test uses
a fresh isolated Codex CLI invocation with only this MCP enabled, sends a nonce
prompt, waits for the expected reply, restarts the browser process, and confirms
the profile remains authenticated.
