from backend.services.codex_recovery import (
    get_native_goal_handoff,
    native_goal_handoff,
    with_native_goal_handoff,
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
