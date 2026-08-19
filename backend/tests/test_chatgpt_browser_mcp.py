import json
from pathlib import Path

import pytest

from backend.mcp import ccm_chatgpt_browser_server as browser_mcp
from backend.services.chatgpt_browser import ChatGPTBrowserError


EXPECTED_TOOLS = {
    "chatgpt_status",
    "chatgpt_open_conversation",
    "chatgpt_send_message",
    "chatgpt_wait_for_reply",
    "chatgpt_conversation_url",
}


def test_chatgpt_browser_mcp_registers_only_narrow_tools():
    assert set(browser_mcp.mcp._tool_manager._tools) == EXPECTED_TOOLS


def test_browser_config_requires_absolute_profile(tmp_path):
    with pytest.raises(ChatGPTBrowserError, match="absolute"):
        browser_mcp.configure(profile_dir=Path("relative-profile"))


@pytest.mark.asyncio
async def test_safe_call_returns_structured_browser_error(monkeypatch, tmp_path):
    class FakeSession:
        async def status(self):
            raise ChatGPTBrowserError("login_required", "Please log in")

    monkeypatch.setattr(browser_mcp, "_session", FakeSession())
    result = json.loads(await browser_mcp.chatgpt_status())

    assert result == {
        "success": False,
        "error_code": "login_required",
        "error": "Please log in",
    }


@pytest.mark.asyncio
async def test_safe_call_hides_unexpected_exception_detail(monkeypatch):
    class FakeSession:
        async def status(self):
            raise RuntimeError("cookie=secret-value")

    monkeypatch.setattr(browser_mcp, "_session", FakeSession())
    result = json.loads(await browser_mcp.chatgpt_status())

    assert result == {
        "success": False,
        "error_code": "browser_failure",
        "error": "ChatGPT browser operation failed",
    }
