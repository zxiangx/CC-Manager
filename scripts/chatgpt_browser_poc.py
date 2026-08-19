#!/usr/bin/env python3
"""Manual login and smoke-test CLI for the ChatGPT Browser MCP prototype."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from backend.services.chatgpt_browser import (
    CHATGPT_START_URL,
    ChatGPTBrowserConfig,
    ChatGPTBrowserError,
    ChatGPTBrowserSession,
)


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--executable-path")
    parser.add_argument("--start-url", default=CHATGPT_START_URL)
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Open a headed browser and wait for login")
    login.add_argument("--timeout", type=float, default=1800)

    subparsers.add_parser("status", help="Check persistent profile login state")

    send = subparsers.add_parser("send", help="Send a message and optionally wait")
    send.add_argument("message")
    send.add_argument("--wait", action="store_true")
    send.add_argument("--timeout", type=float, default=180)

    wait = subparsers.add_parser("wait", help="Wait for the latest reply")
    wait.add_argument("--timeout", type=float, default=180)

    open_parser = subparsers.add_parser("open", help="Open a conversation URL")
    open_parser.add_argument("url", nargs="?")
    return parser


async def _run(args: argparse.Namespace) -> int:
    headed = args.command == "login"
    config = ChatGPTBrowserConfig(
        profile_dir=args.profile_dir,
        headless=not headed,
        executable_path=args.executable_path,
        start_url=args.start_url,
    )
    try:
        async with ChatGPTBrowserSession(config) as session:
            if args.command == "login":
                await session.open_conversation(args.start_url)
                deadline = time.monotonic() + args.timeout
                last_state: str | None = None
                while time.monotonic() < deadline:
                    result = await session.status()
                    if result["state"] != last_state:
                        _emit(result)
                        last_state = result["state"]
                    if result["authenticated"]:
                        return 0
                    await asyncio.sleep(1)
                raise ChatGPTBrowserError(
                    "login_timeout",
                    f"Timed out after {args.timeout:g} seconds waiting for login",
                )
            if args.command == "status":
                _emit(await session.status())
            elif args.command == "open":
                _emit(await session.open_conversation(args.url))
            elif args.command == "send":
                _emit(await session.send_message(args.message))
                if args.wait:
                    _emit(await session.wait_for_reply(args.timeout))
            elif args.command == "wait":
                _emit(await session.wait_for_reply(args.timeout))
            return 0
    except ChatGPTBrowserError as exc:
        _emit(exc.as_dict())
        return 2
    except Exception:
        _emit({
            "success": False,
            "error_code": "browser_failure",
            "error": "ChatGPT browser operation failed",
        })
        return 3


def main() -> int:
    return asyncio.run(_run(build_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
