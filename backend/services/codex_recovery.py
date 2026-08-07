"""Durable recovery markers for Codex turns that cannot be resumed safely."""

from __future__ import annotations

from typing import Any, Mapping


QUARANTINE_REASON_KEY = "codex_quarantine_reason"
QUARANTINED_SESSION_KEY = "codex_quarantined_session_id"
QUARANTINED_SESSIONS_KEY = "codex_quarantined_sessions"
REQUEST_BLOCKED_REASON = "request_blocked"


def is_request_blocked(provider: str | None, message: object) -> bool:
    """Identify the provider terminal that poisons a resumable Codex thread."""

    if (provider or "").lower() != "codex":
        return False
    normalized = " ".join(str(message or "").lower().split())
    return "request blocked" in normalized


def quarantine_metadata(
    metadata: Mapping[str, Any] | None,
    session_id: str | None,
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
    return result


def has_request_blocked_quarantine(
    metadata: Mapping[str, Any] | None,
    *,
    error_message: object = None,
) -> bool:
    """Recognize new durable markers and legacy failed rows."""

    if isinstance(metadata, Mapping):
        if metadata.get(QUARANTINE_REASON_KEY) == REQUEST_BLOCKED_REASON:
            return True
    return "request blocked" in " ".join(
        str(error_message or "").lower().split()
    )


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
