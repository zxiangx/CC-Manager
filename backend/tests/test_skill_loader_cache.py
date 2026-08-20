"""Regression tests for low-latency skill discovery."""

from unittest.mock import patch

from backend.services import skill_loader


def test_parse_skill_accepts_standard_metadata_ccm_extension(tmp_path):
    skill_dir = tmp_path / "skills" / "peer"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: peer\n"
        "description: peer task guidance\n"
        "metadata:\n"
        "  ccm:\n"
        "    always: true\n"
        "    priority: 10\n"
        "    tools: [ccm_read_task]\n"
        "---\n"
        "Read the peer first.\n",
        encoding="utf-8",
    )

    skill = skill_loader.parse_skill(skill_path)

    assert skill is not None
    assert skill.ccm.always is True
    assert skill.ccm.priority == 10
    assert skill.ccm.tools == ["ccm_read_task"]


def test_discover_skills_reuses_parsed_metadata_within_ttl(tmp_path):
    skill_dir = tmp_path / "repo" / "skills" / "fast-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: fast-skill\ndescription: cached\n---\nBody\n",
        encoding="utf-8",
    )
    skill_loader._discovery_cache.clear()

    with patch.object(
        skill_loader,
        "parse_skill",
        wraps=skill_loader.parse_skill,
    ) as parse:
        first = skill_loader.discover_skills(ccm_repo_dir=tmp_path / "repo")
        second = skill_loader.discover_skills(ccm_repo_dir=tmp_path / "repo")

    assert list(first) == ["fast-skill"]
    assert list(second) == ["fast-skill"]
    assert parse.call_count == 1


def test_discover_skills_cache_still_applies_per_call_filters(tmp_path):
    skill_dir = tmp_path / "repo" / "skills" / "role-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: role-skill\n"
        "description: role-specific\n"
        "ccm:\n"
        "  roles: [admin]\n"
        "---\n"
        "Body\n",
        encoding="utf-8",
    )
    skill_loader._discovery_cache.clear()

    assert "role-skill" in skill_loader.discover_skills(
        ccm_repo_dir=tmp_path / "repo", role="admin"
    )
    assert skill_loader.discover_skills(
        ccm_repo_dir=tmp_path / "repo", role="viewer"
    ) == {}
