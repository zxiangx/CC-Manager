import json
import os
import sqlite3
from pathlib import Path

import pytest

from backend.services import codex_shared_state as shared_state_module
from backend.services.codex_shared_state import (
    CodexSharedStateError,
    converge_codex_shared_state,
    prepare_codex_account_projection,
)


THREAD = "019ffbf6-cf8c-71c0-970e-774b0dfe5b3d"


def _rollout(home: Path, body: bytes, *, day: str = "14") -> Path:
    path = home / "sessions" / "2026" / "08" / day / (
        f"rollout-2026-08-{day}T00-00-00-{THREAD}.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _goal_db(
    home: Path,
    *,
    objective: str,
    status: str,
    updated: int,
    deferred: bool = False,
) -> None:
    home.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(home / "goals_1.sqlite")
    db.execute(
        """create table thread_goals (
        thread_id text primary key,
        goal_id text not null,
        objective text not null,
        status text not null,
        token_budget integer,
        tokens_used integer not null,
        time_used_seconds integer not null,
        created_at_ms integer not null,
        updated_at_ms integer not null
        )"""
    )
    db.execute(
        "create table thread_goal_continuation_deferrals ("
        "thread_id text primary key not null references "
        "thread_goals(thread_id) on delete cascade)"
    )
    db.execute(
        "insert into thread_goals values (?, ?, ?, ?, null, 1, 2, 3, ?)",
        (THREAD, f"goal-{updated}", objective, status, updated),
    )
    if deferred:
        db.execute(
            "insert into thread_goal_continuation_deferrals values (?)",
            (THREAD,),
        )
    db.commit()
    db.close()


def test_convergence_keeps_longest_rollout_and_latest_goal(tmp_path: Path):
    account_a = tmp_path / "codex-a"
    account_b = tmp_path / "codex-b"
    _rollout(account_a, b'{"n":1}\n')
    _rollout(account_b, b'{"n":1}\n{"n":2}\n')
    _goal_db(account_a, objective="old", status="blocked", updated=10)
    _goal_db(account_b, objective="new", status="active", updated=20)

    root = tmp_path / "shared"
    result = converge_codex_shared_state(root, [account_a, account_b])

    shared = next((root / "sessions").rglob(f"*{THREAD}.jsonl"))
    assert shared.read_bytes() == b'{"n":1}\n{"n":2}\n'
    db = sqlite3.connect(root / "goals_1.sqlite")
    assert db.execute(
        "select objective, status from thread_goals where thread_id=?", (THREAD,)
    ).fetchone() == ("new", "active")
    assert result["migrated"] is True
    assert (root / "migration.json").is_file()
    for home in (account_a, account_b):
        assert (home / "sessions").is_symlink()
        assert (home / "sessions").resolve() == (root / "sessions").resolve()


def test_diverged_rollout_uses_bound_home_and_preserves_all_evidence(tmp_path: Path):
    account_a = tmp_path / "codex-a"
    account_b = tmp_path / "codex-b"
    _rollout(account_a, b'{"account":"a"}\n')
    _rollout(account_b, b'{"account":"b"}\n')

    root = tmp_path / "shared"
    result = converge_codex_shared_state(
        root,
        [account_a, account_b],
        task_bindings={THREAD: account_a},
    )

    shared = next((root / "sessions").rglob(f"*{THREAD}.jsonl"))
    assert shared.read_bytes() == b'{"account":"a"}\n'
    assert result["diverged_threads"] == [THREAD]
    backup_root = root / result["backup_relative"]
    backups = list(backup_root.rglob(f"*{THREAD}.jsonl"))
    assert [path.read_bytes() for path in backups] == [b'{"account":"b"}\n']
    assert sorted([shared.read_bytes(), *[path.read_bytes() for path in backups]]) == [
        b'{"account":"a"}\n',
        b'{"account":"b"}\n',
    ]


def test_explicit_goal_binding_wins_over_newer_timestamp(tmp_path: Path):
    account_a = tmp_path / "codex-a"
    account_b = tmp_path / "codex-b"
    _rollout(account_a, b'{"account":"a"}\n')
    _rollout(account_b, b'{"account":"a"}\n')
    _goal_db(
        account_a,
        objective="user-confirmed",
        status="blocked",
        updated=10,
        deferred=True,
    )
    _goal_db(
        account_b,
        objective="newer-but-wrong",
        status="active",
        updated=20,
    )

    root = tmp_path / "shared"
    converge_codex_shared_state(
        root,
        [account_a, account_b],
        goal_bindings={THREAD: account_a},
    )

    db = sqlite3.connect(root / "goals_1.sqlite")
    assert db.execute(
        "select objective, status from thread_goals where thread_id=?",
        (THREAD,),
    ).fetchone() == ("user-confirmed", "blocked")
    assert db.execute(
        "select thread_id from thread_goal_continuation_deferrals"
    ).fetchone() == (THREAD,)


def test_convergence_is_idempotent_and_projects_new_empty_account(tmp_path: Path):
    account_a = tmp_path / "codex-a"
    _rollout(account_a, b'{"n":1}\n')
    root = tmp_path / "shared"
    first = converge_codex_shared_state(root, [account_a])
    second = converge_codex_shared_state(root, [account_a])
    assert first["migrated"] is True
    assert second["migrated"] is False

    account_b = tmp_path / "codex-b"
    account_b.mkdir()
    prepare_codex_account_projection(root, account_b)
    assert (account_b / "sessions").resolve() == (root / "sessions").resolve()
    assert (account_b / "archived_sessions").resolve() == (
        root / "archived_sessions"
    ).resolve()


def test_incomplete_no_copy_migration_resumes_from_durable_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    account_a = tmp_path / "codex-a"
    account_b = tmp_path / "codex-b"
    _rollout(account_a, b'{"account":"a"}\n')
    _rollout(account_b, b'{"account":"a"}\n{"more":true}\n')
    root = tmp_path / "shared"
    real_replace = shared_state_module.os.replace
    failed = False

    def interrupted_replace(source, destination):
        nonlocal failed
        if (
            not failed
            and Path(source) == account_a / "sessions"
            and "legacy" in Path(destination).parts
        ):
            failed = True
            raise OSError("simulated deployment interruption")
        return real_replace(source, destination)

    monkeypatch.setattr(shared_state_module.os, "replace", interrupted_replace)
    with pytest.raises(OSError, match="simulated deployment interruption"):
        converge_codex_shared_state(root, [account_a, account_b])

    assert list(root.glob(".migration-stage-*"))
    monkeypatch.setattr(shared_state_module.os, "replace", real_replace)
    result = converge_codex_shared_state(root, [account_a, account_b])

    assert result["migrated"] is True
    assert not list(root.glob(".migration-stage-*"))
    shared = next((root / "sessions").rglob(f"*{THREAD}.jsonl"))
    assert shared.read_bytes() == b'{"account":"a"}\n{"more":true}\n'
    assert (account_a / "sessions").is_symlink()
    assert (account_b / "sessions").is_symlink()


def test_projection_refuses_unmigrated_nonempty_directory(tmp_path: Path):
    root = tmp_path / "shared"
    root.mkdir()
    account = tmp_path / "codex-a"
    _rollout(account, b'{"n":1}\n')
    with pytest.raises(CodexSharedStateError, match="non-empty"):
        prepare_codex_account_projection(root, account)


def test_projection_is_owner_only(tmp_path: Path):
    root = tmp_path / "shared"
    account = tmp_path / "codex-a"
    account.mkdir()
    prepare_codex_account_projection(root, account)
    assert os.stat(root).st_mode & 0o077 == 0
