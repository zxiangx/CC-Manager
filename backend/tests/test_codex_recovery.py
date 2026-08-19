import pytest

from backend.services.codex_recovery import (
    get_native_goal_handoff,
    has_request_blocked_quarantine,
    is_request_blocked,
    native_goal_handoff,
    with_native_goal_handoff,
)


FLAGGED_PROMPT = (
    "Invalid prompt: your prompt was flagged as potentially violating our "
    "usage policy. Please try again with a different prompt."
)


def test_native_goal_handoff_preserves_intent_and_remaining_budget():
    handoff = native_goal_handoff(
        {
            "objective": "finish the migration",
            "status": "blocked",
            "tokenBudget": 1000,
            "tokensUsed": 250,
        },
        source_thread_id="thread-old",
        resume=True,
    )

    assert handoff == {
        "objective": "finish the migration",
        "status": "active",
        "source_thread_id": "thread-old",
        "token_budget": 750,
    }
    metadata = with_native_goal_handoff({"other": True}, handoff)
    assert get_native_goal_handoff(metadata) == handoff
    assert with_native_goal_handoff(metadata, None) == {"other": True}


def test_native_goal_handoff_does_not_copy_terminal_goal():
    assert native_goal_handoff(
        {"objective": "done", "status": "complete"},
        source_thread_id="thread-old",
        resume=False,
    ) is None


@pytest.mark.parametrize(
    "message",
    [
        "Request blocked.",
        FLAGGED_PROMPT,
        "Your prompt was potentially violating our usage policy",
    ],
)
def test_codex_policy_terminals_require_safe_session_recovery(message):
    assert is_request_blocked("codex", message) is True
    assert has_request_blocked_quarantine(None, error_message=message) is True


def test_non_codex_or_unrelated_invalid_prompt_is_not_quarantined():
    assert is_request_blocked("claude", FLAGGED_PROMPT) is False
    assert is_request_blocked("codex", "Invalid prompt: missing input") is False
    assert (
        has_request_blocked_quarantine(
            None,
            error_message="Invalid prompt: missing input",
        )
        is False
    )
