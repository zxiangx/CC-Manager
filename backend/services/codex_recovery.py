"""Durable recovery markers for Codex turns that cannot be resumed safely."""

from __future__ import annotations

from typing import Any, Mapping


QUARANTINE_REASON_KEY = "codex_quarantine_reason"
QUARANTINED_SESSION_KEY = "codex_quarantined_session_id"
QUARANTINED_SESSIONS_KEY = "codex_quarantined_sessions"
REQUEST_BLOCKED_REASON = "request_blocked"
NATIVE_GOAL_HANDOFF_KEY = "codex_native_goal_handoff"
REQUEST_BLOCKED_REPLAY_HINT = (
    "[提示：你之前已经做过一部分该工作，因为触发特殊原因被block了，"
    "现在是我回过头让你重新执行]"
)


def request_blocked_replay_prompt(message: object) -> str:
    """Replay one human request in a clean thread, without prior turn output."""

    request = str(message or "").strip()
    if not request:
        return REQUEST_BLOCKED_REPLAY_HINT
    return f"{request}\n\n{REQUEST_BLOCKED_REPLAY_HINT}"


def _matches_request_blocked_message(message: object) -> bool:
    normalized = " ".join(str(message or "").lower().split())
    return (
        "request blocked" in normalized
        or (
            "invalid prompt" in normalized
            and "your prompt was flagged" in normalized
        )
        or "potentially violating our usage policy" in normalized
    )


def is_request_blocked(provider: str | None, message: object) -> bool:
    """Identify the provider terminal that poisons a resumable Codex thread."""

    if (provider or "").lower() != "codex":
        return False
    return _matches_request_blocked_message(message)


def quarantine_metadata(
    metadata: Mapping[str, Any] | None,
    session_id: str | None,
    *,
    goal_handoff: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return copied Task metadata with one active, auditable quarantine."""

    result = dict(metadata or {})
    result[QUARANTINE_REASON_KEY] = REQUEST_BLOCKED_REASON
    if session_id:
        result[QUARANTINED_SESSION_KEY] = session_id
        prior = result.get(QUARANTINED_SESSIONS_KEY)
        sessions = [str(item) for item in prior] if isinstance(prior, list) else []
        if session_id not in sessions:
            sessions.append(session_id)
        result[QUARANTINED_SESSIONS_KEY] = sessions[-20:]
    if goal_handoff is not None:
        result[NATIVE_GOAL_HANDOFF_KEY] = dict(goal_handoff)
    return result


def native_goal_handoff(
    goal: Mapping[str, Any] | None,
    *,
    source_thread_id: str | None,
    resume: bool,
) -> dict[str, Any] | None:
    """Build a bounded Task-level Goal snapshot for a replacement thread."""

    if not isinstance(goal, Mapping):
        return None
    objective = str(goal.get("objective") or "").strip()
    if not objective:
        return None
    status = str(goal.get("status") or "")
    if status not in {"active", "paused", "blocked"}:
        return None
    result: dict[str, Any] = {
        "objective": objective[:20000],
        "status": "active" if resume or status == "active" else "paused",
    }
    if source_thread_id:
        result["source_thread_id"] = source_thread_id
    token_budget = goal.get("tokenBudget")
    tokens_used = goal.get("tokensUsed")
    if type(token_budget) is int and token_budget > 0:
        remaining = token_budget
        if type(tokens_used) is int and tokens_used > 0:
            remaining = max(1, token_budget - tokens_used)
        result["token_budget"] = remaining
    return result


def get_native_goal_handoff(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(NATIVE_GOAL_HANDOFF_KEY)
    if not isinstance(value, Mapping):
        return None
    objective = str(value.get("objective") or "").strip()
    status = value.get("status")
    if not objective or status not in {"active", "paused"}:
        return None
    result = {
        "objective": objective[:20000],
        "status": status,
    }
    source_thread_id = value.get("source_thread_id")
    if isinstance(source_thread_id, str) and source_thread_id:
        result["source_thread_id"] = source_thread_id
    token_budget = value.get("token_budget")
    if type(token_budget) is int and token_budget > 0:
        result["token_budget"] = token_budget
    return result


def with_native_goal_handoff(
    metadata: Mapping[str, Any] | None,
    handoff: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not metadata and handoff is None:
        return None
    result = dict(metadata or {})
    if handoff is None:
        result.pop(NATIVE_GOAL_HANDOFF_KEY, None)
    else:
        result[NATIVE_GOAL_HANDOFF_KEY] = dict(handoff)
    return result or None


def has_request_blocked_quarantine(
    metadata: Mapping[str, Any] | None,
    *,
    error_message: object = None,
) -> bool:
    """Recognize new durable markers and legacy failed rows."""

    if isinstance(metadata, Mapping):
        if metadata.get(QUARANTINE_REASON_KEY) == REQUEST_BLOCKED_REASON:
            return True
    return _matches_request_blocked_message(error_message)


def clear_active_quarantine(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Clear routing markers after a clean replacement thread is claimed."""

    if not metadata:
        return None
    result = dict(metadata)
    result.pop(QUARANTINE_REASON_KEY, None)
    result.pop(QUARANTINED_SESSION_KEY, None)
    return result
