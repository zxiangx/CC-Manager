import os
from pathlib import Path

import pytest

from backend.services.chatgpt_browser import (
    MAX_MESSAGE_CHARS,
    MAX_REPLY_CHARS,
    ChatGPTBrowserError,
    ProfileLease,
    bound_reply,
    classify_chatgpt_page,
    ensure_private_profile_directory,
    normalize_message,
    public_chatgpt_url,
    validate_chatgpt_url,
)


@pytest.mark.parametrize(
    "url",
    (
        "https://chatgpt.com/",
        "https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc",
        "https://chatgpt.com/?model=gpt-5",
    ),
)
def test_validate_chatgpt_url_accepts_only_chatgpt_https(url):
    assert validate_chatgpt_url(url) == url


@pytest.mark.parametrize(
    "url",
    (
        "http://chatgpt.com/",
        "https://evil.example/",
        "https://chatgpt.com.evil.example/",
        "https://user:pass@chatgpt.com/",
        "file:///tmp/chatgpt.html",
    ),
)
def test_validate_chatgpt_url_rejects_unsafe_targets(url):
    with pytest.raises(ChatGPTBrowserError, match="ChatGPT URL"):
        validate_chatgpt_url(url)


@pytest.mark.parametrize(
    ("url", "expected"),
    (
        (
            "https://chatgpt.com/c/abc?temporary=secret#fragment",
            "https://chatgpt.com/c/abc",
        ),
        ("https://auth.openai.com/log-in?token=secret", None),
        ("not a URL", None),
    ),
)
def test_public_chatgpt_url_never_exposes_queries_or_external_auth_urls(url, expected):
    assert public_chatgpt_url(url) == expected


def test_private_profile_directory_is_absolute_and_mode_0700(tmp_path):
    profile = ensure_private_profile_directory(tmp_path / "profile")

    assert profile.is_dir()
    assert profile.is_absolute()
    assert profile.stat().st_mode & 0o777 == 0o700


def test_private_profile_directory_rejects_symlink_component(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(ChatGPTBrowserError, match="symlink"):
        ensure_private_profile_directory(linked / "profile")


def test_profile_lease_rejects_concurrent_owner(tmp_path):
    profile = ensure_private_profile_directory(tmp_path / "profile")

    with ProfileLease(profile):
        with pytest.raises(ChatGPTBrowserError, match="already in use"):
            with ProfileLease(profile):
                raise AssertionError("unreachable")


def test_normalize_message_bounds_and_preserves_text():
    assert normalize_message(" hello \n") == "hello"
    with pytest.raises(ChatGPTBrowserError, match="empty"):
        normalize_message(" \n ")
    with pytest.raises(ChatGPTBrowserError, match="too large"):
        normalize_message("x" * (MAX_MESSAGE_CHARS + 1))


def test_reply_is_bounded_without_losing_prefix():
    text, truncated = bound_reply("x" * (MAX_REPLY_CHARS + 100))

    assert len(text) == MAX_REPLY_CHARS
    assert text == "x" * MAX_REPLY_CHARS
    assert truncated is True


@pytest.mark.parametrize(
    ("url", "composer_visible", "login_visible", "expected"),
    (
        ("https://chatgpt.com/", True, False, "authenticated"),
        ("https://chatgpt.com/auth/login", False, True, "login_required"),
        ("https://chatgpt.com/", False, True, "login_required"),
        ("https://chatgpt.com/", False, False, "unknown"),
    ),
)
def test_classify_chatgpt_page(
    url,
    composer_visible,
    login_visible,
    expected,
):
    assert classify_chatgpt_page(
        url=url,
        composer_visible=composer_visible,
        login_visible=login_visible,
    ) == expected


def test_profile_lease_file_is_private(tmp_path):
    profile = ensure_private_profile_directory(tmp_path / "profile")
    with ProfileLease(profile):
        lock_path = profile.parent / f".{profile.name}.lock"
        assert lock_path.stat().st_mode & 0o777 == 0o600
        assert os.path.isfile(lock_path)
