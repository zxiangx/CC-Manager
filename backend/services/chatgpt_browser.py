"""Persistent, narrow ChatGPT browser automation for the CCM prototype.

This module intentionally automates the public web UI.  It never reads or
returns cookies, browser storage, passwords, or ChatGPT's private HTTP traffic.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit


CHATGPT_START_URL = "https://chatgpt.com/"
MAX_MESSAGE_CHARS = 100_000
MAX_REPLY_CHARS = 200_000
DEFAULT_TIMEOUT_SECONDS = 120.0
_POLL_SECONDS = 0.5
_CONVERSATION_PATH_RE = re.compile(r"^/c/[A-Za-z0-9-]+/?$")


class ChatGPTBrowserError(RuntimeError):
    """Structured browser error safe to return through MCP."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {"success": False, "error_code": self.code, "error": self.message}


def validate_chatgpt_url(url: str) -> str:
    """Accept only the fixed HTTPS ChatGPT origin."""

    value = str(url or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ChatGPTBrowserError("invalid_url", "Invalid ChatGPT URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "chatgpt.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise ChatGPTBrowserError(
            "invalid_url",
            "ChatGPT URL must use the fixed https://chatgpt.com origin",
        )
    return value


def public_chatgpt_url(url: str) -> str | None:
    """Return only a non-secret ChatGPT origin/path, or ``None`` off-origin."""

    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "chatgpt.com":
        return None
    return f"https://chatgpt.com{parsed.path or '/'}"


def normalize_message(message: str) -> str:
    value = str(message or "").strip()
    if not value:
        raise ChatGPTBrowserError("empty_message", "ChatGPT message cannot be empty")
    if len(value) > MAX_MESSAGE_CHARS:
        raise ChatGPTBrowserError(
            "message_too_large",
            f"ChatGPT message is too large (maximum {MAX_MESSAGE_CHARS} characters)",
        )
    return value


def bound_reply(reply: str) -> tuple[str, bool]:
    value = str(reply or "")
    if len(value) <= MAX_REPLY_CHARS:
        return value, False
    return value[:MAX_REPLY_CHARS], True


def classify_chatgpt_page(
    *,
    url: str,
    composer_visible: bool,
    login_visible: bool,
) -> Literal["authenticated", "login_required", "unknown"]:
    if composer_visible:
        return "authenticated"
    path = urlsplit(url).path.lower()
    if path.startswith("/auth/") or login_visible:
        return "login_required"
    return "unknown"


def _path_components(path: Path) -> list[Path]:
    components: list[Path] = []
    current = path
    while current != current.parent:
        components.append(current)
        current = current.parent
    components.reverse()
    return components


def ensure_private_profile_directory(path: str | os.PathLike[str]) -> Path:
    """Create an absolute 0700 directory without traversing symlinks."""

    profile = Path(path).expanduser()
    if not profile.is_absolute():
        raise ChatGPTBrowserError(
            "unsafe_profile",
            "ChatGPT browser profile path must be absolute",
        )
    for component in _path_components(profile):
        try:
            info = component.lstat()
        except FileNotFoundError:
            component.mkdir(mode=0o700)
            info = component.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ChatGPTBrowserError(
                "unsafe_profile",
                f"ChatGPT browser profile contains a symlink: {component}",
            )
        if not stat.S_ISDIR(info.st_mode):
            raise ChatGPTBrowserError(
                "unsafe_profile",
                f"ChatGPT browser profile component is not a directory: {component}",
            )
    os.chmod(profile, 0o700)
    return profile


class ProfileLease:
    """Exclusive process lease for one persistent browser profile."""

    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self.lock_path = profile_dir.parent / f".{profile_dir.name}.lock"
        self._fd: int | None = None

    def acquire(self) -> "ProfileLease":
        ensure_private_profile_directory(self.profile_dir.parent)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise ChatGPTBrowserError(
                "profile_lock_failed",
                f"Could not open ChatGPT profile lock: {exc}",
            ) from exc
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            os.fsync(fd)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise ChatGPTBrowserError(
                    "profile_busy",
                    "ChatGPT browser profile is already in use",
                ) from exc
            raise ChatGPTBrowserError(
                "profile_lock_failed",
                f"Could not lock ChatGPT browser profile: {exc}",
            ) from exc
        self._fd = fd
        return self

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> "ProfileLease":
        return self.acquire()

    def __exit__(self, *_args: Any) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class ChatGPTBrowserConfig:
    profile_dir: Path
    headless: bool = True
    executable_path: str | None = None
    start_url: str = CHATGPT_START_URL
    launch_timeout_ms: int = 30_000

    def normalized(self) -> "ChatGPTBrowserConfig":
        profile = ensure_private_profile_directory(self.profile_dir)
        start_url = validate_chatgpt_url(self.start_url)
        executable = self.executable_path
        if executable:
            executable_path = Path(executable)
            if not executable_path.is_absolute() or not executable_path.is_file():
                raise ChatGPTBrowserError(
                    "invalid_browser",
                    "Configured Chrome executable must be an existing absolute file",
                )
            executable = str(executable_path)
        timeout = int(self.launch_timeout_ms)
        if timeout < 1_000 or timeout > 300_000:
            raise ChatGPTBrowserError(
                "invalid_timeout",
                "Browser launch timeout must be between 1000 and 300000 ms",
            )
        return ChatGPTBrowserConfig(
            profile_dir=profile,
            headless=bool(self.headless),
            executable_path=executable,
            start_url=start_url,
            launch_timeout_ms=timeout,
        )


class ChatGPTBrowserSession:
    """One Playwright owner for a persistent ChatGPT web profile."""

    _COMPOSER_SELECTORS = (
        "#prompt-textarea",
        'textarea[data-testid="prompt-textarea"]',
        'textarea[placeholder*="Message"]',
        'textarea[placeholder*="消息"]',
        'div[contenteditable="true"][data-virtualkeyboard="true"]',
    )
    _SEND_SELECTORS = (
        'button[data-testid="send-button"]',
        'button[aria-label="Send prompt"]',
        'button[aria-label="发送提示"]',
        'button[aria-label="Send message"]',
    )
    _STOP_SELECTORS = (
        'button[data-testid="stop-button"]',
        'button[aria-label="Stop streaming"]',
        'button[aria-label="停止生成"]',
    )
    _ASSISTANT_SELECTOR = '[data-message-author-role="assistant"]'
    _USER_SELECTOR = '[data-message-author-role="user"]'

    def __init__(self, config: ChatGPTBrowserConfig):
        self.config = config.normalized()
        self._lease = ProfileLease(self.config.profile_dir)
        self._playwright: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._expected_assistant_count: int | None = None

    async def start(self) -> None:
        if self._context is not None:
            return
        self._lease.acquire()
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            launch: dict[str, Any] = {
                "headless": self.config.headless,
                "timeout": self.config.launch_timeout_ms,
                "args": [
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                "viewport": {"width": 1440, "height": 960},
            }
            if self.config.executable_path:
                launch["executable_path"] = self.config.executable_path
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self.config.profile_dir),
                **launch,
            )
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
            if not str(self._page.url).startswith("https://chatgpt.com"):
                await self._page.goto(
                    self.config.start_url,
                    wait_until="domcontentloaded",
                    timeout=self.config.launch_timeout_ms,
                )
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        context, self._context = self._context, None
        playwright, self._playwright = self._playwright, None
        self._page = None
        try:
            if context is not None:
                await context.close()
        finally:
            try:
                if playwright is not None:
                    await playwright.stop()
            finally:
                self._lease.release()

    async def __aenter__(self) -> "ChatGPTBrowserSession":
        await self.start()
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.close()

    def _require_page(self) -> Any:
        if self._page is None:
            raise ChatGPTBrowserError("browser_not_started", "Browser is not started")
        return self._page

    async def _first_visible(self, selectors: tuple[str, ...]) -> Any | None:
        page = self._require_page()
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if await locator.is_visible(timeout=500):
                    return locator
            except Exception:
                continue
        return None

    async def _login_visible(self) -> bool:
        page = self._require_page()
        names = re.compile(r"^(Log in|Sign up|登录|注册)$", re.IGNORECASE)
        for role in ("button", "link"):
            try:
                if await page.get_by_role(role, name=names).first.is_visible(timeout=500):
                    return True
            except Exception:
                continue
        return False

    async def status(self) -> dict[str, Any]:
        await self.start()
        page = self._require_page()
        state = classify_chatgpt_page(
            url=str(page.url),
            composer_visible=(await self._first_visible(self._COMPOSER_SELECTORS))
            is not None,
            login_visible=await self._login_visible(),
        )
        return {
            "success": True,
            "state": state,
            "authenticated": state == "authenticated",
            "login_required": state == "login_required",
            # Login can temporarily navigate to an OpenAI authentication
            # origin. Never return that URL or any query/fragment values.
            "url": public_chatgpt_url(str(page.url)),
        }

    async def _require_authenticated(self) -> Any:
        status = await self.status()
        if status["state"] != "authenticated":
            code = "login_required" if status["login_required"] else "page_not_ready"
            raise ChatGPTBrowserError(
                code,
                "ChatGPT login is required in the persistent browser profile"
                if code == "login_required"
                else "ChatGPT page is not ready for messages",
            )
        return self._require_page()

    async def open_conversation(self, url: str | None = None) -> dict[str, Any]:
        await self.start()
        target = validate_chatgpt_url(url or CHATGPT_START_URL)
        parsed = urlsplit(target)
        if parsed.query or parsed.fragment:
            raise ChatGPTBrowserError(
                "invalid_conversation_url",
                "ChatGPT conversation URLs cannot contain query parameters or fragments",
            )
        if parsed.path not in ("", "/") and not _CONVERSATION_PATH_RE.fullmatch(
            parsed.path
        ):
            raise ChatGPTBrowserError(
                "invalid_conversation_url",
                "Only the ChatGPT home page or a /c/<conversation-id> URL is allowed",
            )
        page = self._require_page()
        await page.goto(
            target,
            wait_until="domcontentloaded",
            timeout=self.config.launch_timeout_ms,
        )
        return await self.status()

    async def send_message(self, message: str) -> dict[str, Any]:
        value = normalize_message(message)
        page = await self._require_authenticated()
        composer = await self._first_visible(self._COMPOSER_SELECTORS)
        if composer is None:
            raise ChatGPTBrowserError("composer_missing", "ChatGPT composer is unavailable")
        assistants_before = await page.locator(self._ASSISTANT_SELECTOR).count()
        users_before = await page.locator(self._USER_SELECTOR).count()
        await composer.fill(value)
        send = await self._first_visible(self._SEND_SELECTORS)
        if send is None:
            raise ChatGPTBrowserError("send_missing", "ChatGPT send button is unavailable")
        await send.click()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if await page.locator(self._USER_SELECTOR).count() > users_before:
                self._expected_assistant_count = assistants_before + 1
                return {
                    "success": True,
                    "sent": True,
                    "url": public_chatgpt_url(str(page.url)),
                }
            await asyncio.sleep(_POLL_SECONDS)
        raise ChatGPTBrowserError(
            "send_unconfirmed",
            "ChatGPT did not confirm the sent message in the conversation",
        )

    async def wait_for_reply(
        self,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        page = await self._require_authenticated()
        timeout = float(timeout_seconds)
        if timeout < 1 or timeout > 1800:
            raise ChatGPTBrowserError(
                "invalid_timeout",
                "Reply timeout must be between 1 and 1800 seconds",
            )
        assistant_messages = page.locator(self._ASSISTANT_SELECTOR)
        target_count = self._expected_assistant_count
        if target_count is None:
            target_count = max(1, await assistant_messages.count())
        deadline = time.monotonic() + timeout
        last_text = ""
        stable_reads = 0
        while time.monotonic() < deadline:
            count = await assistant_messages.count()
            if count >= target_count:
                current = (await assistant_messages.nth(count - 1).inner_text()).strip()
                if current and current == last_text:
                    stable_reads += 1
                else:
                    last_text = current
                    stable_reads = 0
                still_streaming = await self._first_visible(self._STOP_SELECTORS)
                if current and stable_reads >= 2 and still_streaming is None:
                    reply, truncated = bound_reply(current)
                    self._expected_assistant_count = None
                    return {
                        "success": True,
                        "reply": reply,
                        "truncated": truncated,
                        "url": public_chatgpt_url(str(page.url)),
                    }
            await asyncio.sleep(_POLL_SECONDS)
        raise ChatGPTBrowserError(
            "reply_timeout",
            f"Timed out after {timeout:g} seconds waiting for ChatGPT reply",
        )

    async def conversation_url(self) -> dict[str, Any]:
        page = await self._require_authenticated()
        url = public_chatgpt_url(str(page.url))
        if url is None or not _CONVERSATION_PATH_RE.fullmatch(urlsplit(url).path):
            raise ChatGPTBrowserError(
                "conversation_unavailable",
                "The browser is not currently on a ChatGPT conversation",
            )
        return {"success": True, "url": url}
