"""Tests for the project-scoped AGENTS.md editor API."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_project_creation():
    with patch("backend.api.projects._clone_repo", new_callable=AsyncMock), patch(
        "backend.api.projects._init_local_repo", new_callable=AsyncMock
    ):
        yield


async def _project_with_root(client, session_factory, root, name: str) -> int:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    project_id = response.json()["id"]
    async with session_factory() as db:
        from backend.models.project import Project

        project = await db.get(Project, project_id)
        project.local_path = str(root)
        project.status = "ready"
        await db.commit()
    return project_id


@pytest.mark.asyncio
async def test_agents_md_editor_reads_missing_file_and_creates_it(
    client, session_factory, tmp_path, mock_project_creation
):
    project_id = await _project_with_root(
        client, session_factory, tmp_path, "agents-create"
    )

    response = await client.get(f"/api/projects/{project_id}/agents-md")
    assert response.status_code == 200
    assert response.json() == {"content": "", "exists": False}

    response = await client.put(
        f"/api/projects/{project_id}/agents-md",
        json={"content": "# Local rules\n"},
    )
    assert response.status_code == 200
    assert response.json() == {"content": "# Local rules\n", "exists": True}
    assert (tmp_path / "AGENTS.md").read_text() == "# Local rules\n"


@pytest.mark.asyncio
async def test_agents_md_editor_updates_canonical_claude_symlink(
    client, session_factory, tmp_path, mock_project_creation
):
    (tmp_path / "CLAUDE.md").write_text("old")
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
    project_id = await _project_with_root(
        client, session_factory, tmp_path, "agents-symlink"
    )

    response = await client.put(
        f"/api/projects/{project_id}/agents-md",
        json={"content": "shared instructions"},
    )

    assert response.status_code == 200
    assert (tmp_path / "AGENTS.md").is_symlink()
    assert (tmp_path / "CLAUDE.md").read_text() == "shared instructions"


@pytest.mark.asyncio
async def test_agents_md_editor_rejects_unsafe_symlink(
    client, session_factory, tmp_path, mock_project_creation
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("do not touch")
    (project_root / "AGENTS.md").symlink_to(outside)
    project_id = await _project_with_root(
        client, session_factory, project_root, "agents-unsafe-link"
    )

    response = await client.put(
        f"/api/projects/{project_id}/agents-md",
        json={"content": "overwrite"},
    )

    assert response.status_code == 400
    assert "unsafe symlink" in response.json()["detail"]
    assert outside.read_text() == "do not touch"


@pytest.mark.asyncio
async def test_agents_md_editor_enforces_size_limit(
    client, session_factory, tmp_path, mock_project_creation
):
    project_id = await _project_with_root(
        client, session_factory, tmp_path, "agents-size"
    )

    response = await client.put(
        f"/api/projects/{project_id}/agents-md",
        json={"content": "x" * (1024 * 1024 + 1)},
    )

    assert response.status_code == 413
    assert not (tmp_path / "AGENTS.md").exists()


@pytest.mark.asyncio
async def test_agents_md_editor_rejects_missing_project_root(
    client, session_factory, tmp_path, mock_project_creation
):
    missing = tmp_path / "missing"
    project_id = await _project_with_root(
        client, session_factory, missing, "agents-missing-root"
    )

    response = await client.get(f"/api/projects/{project_id}/agents-md")

    assert response.status_code == 400
    assert response.json()["detail"] == "Project directory does not exist"
