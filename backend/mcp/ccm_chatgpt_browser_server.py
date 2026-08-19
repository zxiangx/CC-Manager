"""Opt-in STDIO MCP adapter for one persistent ChatGPT browser profile."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from backend.services.chatgpt_browser import (
    CHATGPT_START_URL,
    ChatGPTBrowserConfig,
    ChatGPTBrowserError,
    ChatGPTBrowserSession,
)


logger = logging.getLogger(__name__)
mcp = FastMCP(
    "ccm-chatgpt-browser",
    instructions=(
        "Operate only the persistent ChatGPT web profile. Never request or "
        "expose passwords, cookies, tokens, or browser storage. Stop and ask "
        "the user to log in when a tool reports login_required."
    ),
)

_config = ChatGPTBrowserConfig(
    profile_dir=Path.home() / ".local" / "share" / "ccm" / "chatgpt-browser-poc" / "profile",
)
_session: ChatGPTBrowserSession | Any | None = None


def configure(
    *,
    profile_dir: Path,
    headless: bool = True,
    executable_path: str | None = None,
    start_url: str = CHATGPT_START_URL,
) -> None:
    global _config, _session
    if _session is not None:
        raise ChatGPTBrowserError(
            "browser_already_configured",
            "ChatGPT browser session has already started",
        )
    _config = ChatGPTBrowserConfig(
        profile_dir=profile_dir,
        headless=headless,
        executable_path=executable_path,
        start_url=start_url,
    ).normalized()


def _get_session() -> ChatGPTBrowserSession:
    global _session
    if _session is None:
        _session = ChatGPTBrowserSession(_config)
    return _session


async def _safe_call(operation: Callable[[], Awaitable[dict[str, Any]]]) -> str:
    try:
        result = await operation()
    except ChatGPTBrowserError as exc:
        result = exc.as_dict()
    except Exception:
        logger.exception("Unexpected ChatGPT browser operation failure")
        result = {
            "success": False,
            "error_code": "browser_failure",
            "error": "ChatGPT browser operation failed",
        }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def chatgpt_status() -> str:
    """Check whether the persistent ChatGPT browser profile is authenticated."""

    return await _safe_call(_get_session().status)


@mcp.tool()
async def chatgpt_open_conversation(url: str | None = None) -> str:
    """Open ChatGPT home or one exact https://chatgpt.com/c/... conversation."""

    return await _safe_call(lambda: _get_session().open_conversation(url))


@mcp.tool()
async def chatgpt_send_message(message: str) -> str:
    """Send one user-approved text message in the current ChatGPT conversation."""

    return await _safe_call(lambda: _get_session().send_message(message))


@mcp.tool()
async def chatgpt_wait_for_reply(timeout_seconds: float = 120) -> str:
    """Wait for the current ChatGPT response to finish and return its text."""

    return await _safe_call(
        lambda: _get_session().wait_for_reply(timeout_seconds),
    )


@mcp.tool()
async def chatgpt_conversation_url() -> str:
    """Return the current ChatGPT conversation URL without browser secrets."""

    return await _safe_call(_get_session().conversation_url)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CCM ChatGPT Browser MCP prototype")
    parser.add_argument("--profile-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true", default=True)
    mode.add_argument("--headed", action="store_false", dest="headless")
    parser.add_argument("--executable-path")
    parser.add_argument("--start-url", default=CHATGPT_START_URL)
    return parser


if __name__ == "__main__":
    args = _parser().parse_args()
    configure(
        profile_dir=args.profile_dir,
        headless=args.headless,
        executable_path=args.executable_path,
        start_url=args.start_url,
    )
    mcp.run(transport="stdio")
