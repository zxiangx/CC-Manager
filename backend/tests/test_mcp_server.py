"""Tests for MCP Skills Server — tool registration and HTTP calls."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import backend.mcp.ccm_skills_server as mcp_mod


@pytest.fixture(autouse=True)
def _set_mcp_globals():
    mcp_mod._TASK_ID = 42
    mcp_mod._API_BASE = "http://localhost:9999"
    yield
    mcp_mod._TASK_ID = 0
    mcp_mod._API_BASE = "http://localhost:8000"


def test_mcp_server_tools_registered():
    tools = mcp_mod.mcp._tool_manager._tools
    names = set(tools.keys())
    assert "create_monitor" in names
    assert "check_monitors" in names
    assert "stop_monitor" in names
    assert "ccm_pause_goal" in names
    assert "ccm_resume_goal" in names
    assert "ccm_update_goal" in names
    assert "ccm_list_tasks" in names
    assert "ccm_read_task" in names
    assert "ccm_send_task_message" in names


def test_peer_task_access_is_owner_scoped_with_legacy_project_fallback():
    assert mcp_mod._can_access_peer_task(
        {"id": 42, "created_by": 7, "project_id": 1},
        {"id": 48, "created_by": 7, "project_id": 2},
    )
    assert not mcp_mod._can_access_peer_task(
        {"id": 42, "created_by": 7, "project_id": 1},
        {"id": 48, "created_by": 8, "project_id": 1},
    )
    assert mcp_mod._can_access_peer_task(
        {"id": 42, "created_by": None, "project_id": 1, "worker_id": None},
        {"id": 48, "created_by": None, "project_id": 1, "worker_id": None},
    )
    assert not mcp_mod._can_access_peer_task(
        {"id": 42, "created_by": None, "project_id": 1, "worker_id": None},
        {"id": 48, "created_by": None, "project_id": 2, "worker_id": None},
    )


@pytest.mark.asyncio
async def test_list_tasks_filters_by_owner_project_and_query():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = [
        {"id": 48, "title": "Broken GLM", "status": "completed", "created_by": 7, "project_id": 3},
        {"id": 49, "title": "Other project", "status": "completed", "created_by": 7, "project_id": 4},
        {"id": 50, "title": "Other owner GLM", "status": "completed", "created_by": 8, "project_id": 3},
    ]
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)

    source = {"id": 42, "created_by": 7, "project_id": 3}
    with patch.object(mcp_mod, "_get_task_data", AsyncMock(return_value=source)), patch(
        "backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=client
    ):
        result = json.loads(await mcp_mod.ccm_list_tasks(query="GLM"))

    assert result["success"] is True
    assert [task["task_id"] for task in result["tasks"]] == [48]


@pytest.mark.asyncio
async def test_read_task_returns_conversation_without_tool_noise_by_default():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = [
        {"id": 1, "role": "user", "event_type": "user_message", "content": "check it"},
        {"id": 2, "role": "assistant", "event_type": "tool_use", "tool_name": "Bash", "tool_input": "pwd"},
        {"id": 3, "role": "assistant", "event_type": "message", "content": "fixed"},
    ]
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    target = {"id": 48, "title": "Broken GLM", "status": "completed"}

    with patch.object(mcp_mod, "_get_peer_task", AsyncMock(return_value=({}, target))), patch(
        "backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=client
    ):
        result = json.loads(await mcp_mod.ccm_read_task(48))

    assert [message["id"] for message in result["messages"]] == [1, 3]
    assert result["task"]["task_id"] == 48


@pytest.mark.asyncio
async def test_send_task_message_injects_into_active_target():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"ok": True, "delivery": "steer"}
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    target = {"id": 48, "title": "Active", "status": "in_progress"}

    with patch.object(mcp_mod, "_get_peer_task", AsyncMock(return_value=({}, target))), patch(
        "backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=client
    ):
        result = json.loads(await mcp_mod.ccm_send_task_message(48, "report status"))

    assert result["success"] is True
    assert result["delivery"] == "steer"
    client.post.assert_awaited_once_with(
        "http://localhost:9999/api/tasks/48/inject",
        headers={},
        json={"message": "report status"},
    )


def test_goal_control_tools_are_removed_without_codex_launch_flag():
    tools = mcp_mod.mcp._tool_manager._tools
    original = dict(tools)
    try:
        mcp_mod._configure_goal_control_tools(False)
        assert "ccm_pause_goal" not in tools
        assert "ccm_resume_goal" not in tools
        assert "ccm_update_goal" not in tools
    finally:
        tools.clear()
        tools.update(original)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "expected_json", "queued", "expected_status"),
    [
        (
            mcp_mod.ccm_pause_goal,
            {"status": "paused", "finish_current_turn": True},
            False,
            "paused",
        ),
        (
            mcp_mod.ccm_resume_goal,
            {"status": "active"},
            True,
            "resume_requested",
        ),
    ],
)
async def test_goal_control_tools_call_task_scoped_endpoint(
    tool,
    expected_json,
    queued,
    expected_status,
):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "goal": {"status": expected_json["status"]},
        "queued": queued,
    }
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.patch = AsyncMock(return_value=response)

    with patch(
        "backend.mcp.ccm_skills_server.httpx.AsyncClient",
        return_value=client,
    ):
        result = json.loads(await tool())

    assert result["success"] is True
    assert result["status"] == expected_status
    client.patch.assert_awaited_once_with(
        "http://localhost:9999/api/tasks/42/native-goal",
        headers={},
        json=expected_json,
    )


@pytest.mark.asyncio
async def test_update_goal_tool_changes_objective_without_delete_capability():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "goal": {"objective": "new objective", "status": "paused"},
        "queued": False,
    }
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.patch = AsyncMock(return_value=response)

    with patch(
        "backend.mcp.ccm_skills_server.httpx.AsyncClient",
        return_value=client,
    ):
        result = json.loads(await mcp_mod.ccm_update_goal("new objective"))

    assert result == {
        "success": True,
        "objective": "new objective",
        "status": "paused",
        "message": "Goal objective updated.",
    }
    client.patch.assert_awaited_once_with(
        "http://localhost:9999/api/tasks/42/native-goal",
        headers={},
        json={"objective": "new objective"},
    )
    assert "ccm_clear_goal" not in mcp_mod.mcp._tool_manager._tools
    assert "ccm_delete_goal" not in mcp_mod.mcp._tool_manager._tools


def test_api_url():
    assert mcp_mod._api_url("/monitor-sessions") == "http://localhost:9999/api/tasks/42/monitor-sessions"
    assert mcp_mod._api_url("/monitor-sessions/5") == "http://localhost:9999/api/tasks/42/monitor-sessions/5"


@pytest.mark.asyncio
async def test_create_monitor_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 7}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=mock_client):
        result = await mcp_mod.create_monitor("build progress", "tail -f build.log", 60, 10)

    data = json.loads(result)
    assert data["success"] is True
    assert data["monitor_id"] == 7
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_check_monitors_returns_sessions():
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"id": 1, "description": "test", "status": "running", "checks_done": 3, "max_checks": 50, "last_summary": "ok"},
    ]
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=mock_client):
        result = await mcp_mod.check_monitors()

    data = json.loads(result)
    assert data["success"] is True
    assert len(data["monitors"]) == 1
    assert data["monitors"][0]["monitor_id"] == 1


@pytest.mark.asyncio
async def test_check_monitors_empty():
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=mock_client):
        result = await mcp_mod.check_monitors()

    data = json.loads(result)
    assert data["success"] is True
    assert data["monitors"] == []
    assert "没有活跃" in data["message"]


@pytest.mark.asyncio
async def test_stop_monitor_success():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=mock_client):
        result = await mcp_mod.stop_monitor(5)

    data = json.loads(result)
    assert data["success"] is True
    assert data["status"] == "cancelled"


@pytest.mark.asyncio
async def test_create_monitor_api_error():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=mock_client):
        result = await mcp_mod.create_monitor("test")

    data = json.loads(result)
    assert data["success"] is False
    assert "Connection refused" in data["error"]


@pytest.mark.asyncio
async def test_check_monitors_api_error():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=mock_client):
        result = await mcp_mod.check_monitors()

    data = json.loads(result)
    assert data["success"] is False
    assert "timeout" in data["error"]


@pytest.mark.asyncio
async def test_stop_monitor_api_error():
    mock_client = AsyncMock()
    mock_client.delete = AsyncMock(side_effect=Exception("not found"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.mcp.ccm_skills_server.httpx.AsyncClient", return_value=mock_client):
        result = await mcp_mod.stop_monitor(99)

    data = json.loads(result)
    assert data["success"] is False
    assert "not found" in data["error"]


@pytest.mark.asyncio
async def test_codex_cannot_read_monitor_skill():
    with patch.object(
        mcp_mod,
        "_get_task_data",
        new=AsyncMock(return_value={"provider": "codex"}),
    ):
        result = await mcp_mod.ccm_read_skill("monitor")

    data = json.loads(result)
    assert data["success"] is False
    assert "not supported" in data["error"]


@pytest.mark.asyncio
async def test_local_codex_can_read_enabled_monitor_skill(monkeypatch):
    from backend.config import settings
    from backend.services.skill_loader import Skill

    monkeypatch.setattr(settings, "codex_main_mcp_enabled", True)
    task_data = {
        "provider": "codex",
        "worker_id": None,
        "shared_from_id": None,
        "metadata_": {},
        "enabled_skills": {"monitor": True},
    }
    skills = {
        "monitor": Skill(
            name="monitor",
            description="Watch work",
            body="monitor body",
        ),
    }
    with patch.object(
        mcp_mod,
        "_get_task_data",
        new=AsyncMock(return_value=task_data),
    ), patch.object(
        mcp_mod,
        "_monitor_enabled",
        new=AsyncMock(return_value=True),
    ), patch(
        "backend.services.skill_loader.discover_skills",
        return_value=skills,
    ):
        result = json.loads(await mcp_mod.ccm_read_skill("monitor"))

    assert result["success"] is True
    assert result["body"] == "monitor body"


@pytest.mark.asyncio
async def test_worker_managed_codex_cannot_enable_monitor(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "codex_main_mcp_enabled", True)
    get_response = MagicMock()
    get_response.raise_for_status = MagicMock()
    get_response.json.return_value = {
        "provider": "codex",
        "worker_id": None,
        "shared_from_id": None,
        "metadata_": {"ccm_worker_managed_task": True},
        "enabled_skills": {},
    }
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=get_response)
    client.put = AsyncMock()

    with patch(
        "backend.mcp.ccm_skills_server.httpx.AsyncClient",
        return_value=client,
    ):
        result = json.loads(await mcp_mod.ccm_enable_skill("monitor"))

    assert result["success"] is False
    assert "not supported" in result["error"]
    client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_skill_rejects_skill_not_enabled_for_task(monkeypatch):
    from backend.config import settings
    from backend.services.skill_loader import Skill

    monkeypatch.setattr(settings, "codex_main_mcp_enabled", True)
    task_data = {
        "provider": "codex",
        "enabled_skills": {},
    }
    skills = {
        "code-review": Skill(
            name="code-review",
            description="Review changes",
            body="review body",
        ),
    }
    with patch.object(
        mcp_mod,
        "_get_task_data",
        new=AsyncMock(return_value=task_data),
    ), patch(
        "backend.services.skill_loader.discover_skills",
        return_value=skills,
    ):
        result = json.loads(await mcp_mod.ccm_read_skill("code-review"))

    assert result["success"] is False
    assert "not enabled for this task" in result["error"]


@pytest.mark.asyncio
async def test_codex_kill_switch_allows_only_selected_sub_agent_skill(
    monkeypatch,
):
    from backend.config import settings
    from backend.services.skill_loader import Skill

    monkeypatch.setattr(settings, "codex_main_mcp_enabled", False)
    task_data = {
        "provider": "codex",
        # Include a stale ordinary selection to prove the kill switch remains
        # authoritative even if legacy task state bypassed API validation.
        "enabled_skills": {
            "code-review": True,
            "sub-agent": True,
        },
    }
    skills = {
        "code-review": Skill(
            name="code-review",
            description="Review changes",
            body="review body",
        ),
        "sub-agent": Skill(
            name="sub-agent",
            description="Delegate tracked work",
            body="sub-agent body",
        ),
    }
    with patch.object(
        mcp_mod,
        "_get_task_data",
        new=AsyncMock(return_value=task_data),
    ), patch(
        "backend.services.skill_loader.discover_skills",
        return_value=skills,
    ):
        ordinary = json.loads(
            await mcp_mod.ccm_read_skill("code-review")
        )
        sub_agent = json.loads(
            await mcp_mod.ccm_read_skill("sub-agent")
        )

    assert ordinary["success"] is False
    assert "main-task MCP is disabled" in ordinary["error"]
    assert sub_agent["success"] is True
    assert sub_agent["body"] == "sub-agent body"


@pytest.mark.asyncio
async def test_user_skill_read_is_scoped_to_selected_worker_snapshot():
    task_data = {
        "provider": "codex",
        "selected_user_skills": [8],
        "metadata_": {
            "ccm_user_skill_snapshots": [{
                "id": 8,
                "name": "Worker copy",
                "description": "Manager snapshot",
                "content": "full copied body",
            }],
        },
    }
    with patch.object(
        mcp_mod,
        "_get_task_data",
        new=AsyncMock(return_value=task_data),
    ):
        selected = json.loads(await mcp_mod.ccm_read_user_skill(8))
        unselected = json.loads(await mcp_mod.ccm_read_user_skill(9))

    assert selected == {
        "success": True,
        "id": 8,
        "name": "Worker copy",
        "description": "Manager snapshot",
        "content": "full copied body",
    }
    assert unselected["success"] is False
    assert "not selected" in unselected["error"]


@pytest.mark.asyncio
async def test_missing_worker_snapshot_never_falls_back_to_local_user_skill():
    task_data = {
        "provider": "codex",
        "selected_user_skills": [8],
        "metadata_": {"ccm_user_skill_snapshots": []},
    }
    with patch.object(
        mcp_mod,
        "_get_task_data",
        new=AsyncMock(return_value=task_data),
    ), patch(
        "backend.database.async_session",
    ) as local_db:
        result = json.loads(await mcp_mod.ccm_read_user_skill(8))

    assert result["success"] is False
    assert "authoritative task snapshot" in result["error"]
    local_db.assert_not_called()
