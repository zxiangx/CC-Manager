"""Tests for /api/settings/runtime — frontend PTY mode toggle."""
import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, patch

from backend.models.monitor_session import MonitorSession
from backend.models.task import Task


@pytest.mark.asyncio
async def test_get_runtime_settings(client):
    resp = await client.get("/api/settings/runtime")
    assert resp.status_code == 200
    data = resp.json()
    assert "use_pty_mode" in data
    assert "pty_available" in data
    assert "codex_app_server_enabled" in data
    assert "codex_main_mcp_enabled" in data
    assert "codex_monitor_enabled" in data
    assert data["codex_monitor_enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_runtime_settings_keeps_monitor_switch_independent_from_main_mcp(
    client, monkeypatch, enabled,
):
    from backend.config import settings

    monkeypatch.setattr(settings, "codex_main_mcp_enabled", enabled)

    get_resp = await client.get("/api/settings/runtime")
    assert get_resp.status_code == 200
    assert get_resp.json()["codex_main_mcp_enabled"] is enabled
    assert get_resp.json()["codex_monitor_enabled"] is False

    put_resp = await client.put(
        "/api/settings/runtime",
        json={"codex_monitor_enabled": True},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["codex_main_mcp_enabled"] is enabled
    assert put_resp.json()["codex_monitor_enabled"] is True

    get_resp = await client.get("/api/settings/runtime")
    assert get_resp.json()["codex_monitor_enabled"] is True


@pytest.mark.asyncio
async def test_toggle_pty_mode_roundtrip(client):
    from backend.main import instance_manager

    try:
        resp = await client.put(
            "/api/settings/runtime", json={"use_pty_mode": True}
        )
        assert resp.status_code == 200
        body = resp.json()
        # claude_pty installed in dev venv -> enable succeeds
        assert body["pty_available"] is True
        assert body["use_pty_mode"] is True
        assert instance_manager.pty_mode_enabled is True

        resp = await client.put(
            "/api/settings/runtime", json={"use_pty_mode": False}
        )
        assert resp.json()["use_pty_mode"] is False
        assert instance_manager.pty_mode_enabled is False

        # GET reflects current state
        resp = await client.get("/api/settings/runtime")
        assert resp.json()["use_pty_mode"] is False
    finally:
        instance_manager.set_pty_mode(False)


@pytest.mark.asyncio
async def test_toggle_off_drains_idle_sessions(client):
    from unittest.mock import AsyncMock
    from backend.main import instance_manager

    class FakeBackend:
        drain_idle_sessions = AsyncMock(return_value=2)

    old_backend = instance_manager._pty_backend
    old_enabled = instance_manager._pty_enabled
    try:
        instance_manager._pty_backend = FakeBackend()
        instance_manager._pty_enabled = True

        resp = await client.put(
            "/api/settings/runtime", json={"use_pty_mode": False}
        )
        assert resp.status_code == 200
        assert resp.json()["use_pty_mode"] is False
        FakeBackend.drain_idle_sessions.assert_awaited_once()
    finally:
        instance_manager._pty_backend = old_backend
        instance_manager._pty_enabled = old_enabled


@pytest.mark.asyncio
async def test_context_compact_threshold_default_and_update(client):
    from backend.config import settings

    # Default: no DB override -> env default
    resp = await client.get("/api/settings/runtime")
    assert resp.status_code == 200
    assert resp.json()["context_compact_threshold"] == pytest.approx(
        settings.context_compact_threshold
    )

    # Update -> persisted and returned as effective value
    resp = await client.put(
        "/api/settings/runtime", json={"context_compact_threshold": 0.7}
    )
    assert resp.status_code == 200
    assert resp.json()["context_compact_threshold"] == pytest.approx(0.7)

    resp = await client.get("/api/settings/runtime")
    assert resp.json()["context_compact_threshold"] == pytest.approx(0.7)

    # Updating other fields must not clobber the stored threshold
    resp = await client.put(
        "/api/settings/runtime", json={"auto_sort_on_access": True}
    )
    assert resp.json()["context_compact_threshold"] == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_context_compact_threshold_rejects_out_of_range(client):
    for bad in (0.1, 0.99, 2):
        resp = await client.put(
            "/api/settings/runtime", json={"context_compact_threshold": bad}
        )
        assert resp.status_code == 422, f"{bad} should be rejected"


@pytest.mark.asyncio
async def test_disabling_monitor_cancels_running_codex_monitors(
    client,
    session_factory,
):
    enabled = await client.put(
        "/api/settings/runtime",
        json={"codex_monitor_enabled": True},
    )
    assert enabled.status_code == 200

    created = await client.post("/api/tasks", json={
        "title": "monitor owner",
        "description": "test",
        "provider": "codex",
    })
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    async with session_factory() as db:
        await db.execute(
            Task.__table__.update()
            .where(Task.id == task_id)
            .values(status="in_progress")
        )
        monitor = MonitorSession(
            task_id=task_id,
            agent_type="monitor",
            source="ccm",
            provider="codex",
            description="running monitor",
            status="running",
        )
        db.add(monitor)
        await db.commit()
        monitor_id = monitor.id

    from backend.main import dispatcher

    with patch.object(
        dispatcher,
        "stop_monitor_session_process",
        new=AsyncMock(),
    ) as stop:
        disabled = await client.put(
            "/api/settings/runtime",
            json={"codex_monitor_enabled": False},
        )

    assert disabled.status_code == 200
    assert disabled.json()["codex_monitor_enabled"] is False
    stop.assert_awaited_once_with(monitor_id, terminal=True)
    async with session_factory() as db:
        row = await db.scalar(
            select(MonitorSession).where(MonitorSession.id == monitor_id)
        )
    assert row is not None
    assert row.status == "cancelled"
    assert row.completed_at is not None
