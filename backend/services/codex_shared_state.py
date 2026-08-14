"""Canonical Codex rollout/Goal storage shared by isolated account homes."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Iterable, Mapping


class CodexSharedStateError(RuntimeError):
    """Legacy Codex state cannot be converged without losing evidence."""


_THREAD_RE = re.compile(r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\.jsonl$")


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise CodexSharedStateError(f"unsafe shared-state directory: {path}")
    os.chmod(path, 0o700)
    return path.resolve(strict=True)


def _thread_id(path: Path) -> str:
    match = _THREAD_RE.search(path.name)
    if not match:
        raise CodexSharedStateError(f"invalid Codex rollout name: {path.name}")
    return match.group(1).lower()


def _rollouts(home: Path, directory: str) -> list[Path]:
    root = home / directory
    if not root.exists() or root.is_symlink():
        return []
    if not root.is_dir():
        raise CodexSharedStateError(f"unsafe Codex {directory}: {root}")
    paths: list[Path] = []
    for path in root.rglob("rollout-*.jsonl"):
        if path.is_symlink() or not path.is_file():
            raise CodexSharedStateError(f"unsafe Codex rollout: {path}")
        _thread_id(path)
        paths.append(path)
    return paths


def _choose_rollout(
    candidates: list[tuple[Path, Path]],
    bound_home: Path | None,
) -> tuple[Path, Path, bool]:
    sized = [(home, path, path.stat().st_size) for home, path in candidates]
    longest = max(sized, key=lambda row: row[2])

    def is_prefix(smaller: Path, larger: Path) -> bool:
        with smaller.open("rb") as left, larger.open("rb") as right:
            while chunk := left.read(1024 * 1024):
                if right.read(len(chunk)) != chunk:
                    return False
        return True

    comparable = all(
        is_prefix(path, longest[1])
        for _home, path, _size in sized
    )
    if comparable:
        return longest[0], longest[1], False
    if bound_home is not None:
        bound = [row for row in sized if row[0] == bound_home]
        if len(bound) == 1:
            return bound[0][0], bound[0][1], True
    newest = max(sized, key=lambda row: (row[1].stat().st_mtime_ns, row[2]))
    return newest[0], newest[1], True


def _write_private_json(path: Path, payload: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _resume_rollout_migration(root: Path, stage: Path, plan: dict) -> None:
    """Resume the no-copy rollout move described by a durable private plan."""

    phase = str(plan.get("phase") or "staging")
    canonical_stage = stage / "canonical"
    backup = root / str(plan["backup_relative"])

    if phase == "staging":
        for entry in plan["moves"]:
            source = Path(entry["source"])
            destination = canonical_stage / entry["destination"]
            if destination.is_file() and not source.exists():
                continue
            if destination.exists() or not source.is_file() or source.is_symlink():
                raise CodexSharedStateError(
                    f"cannot resume Codex rollout staging: {source} -> {destination}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(source, destination)
        plan["phase"] = phase = "backup"
        _write_private_json(stage / "plan.json", plan)

    if phase == "backup":
        _private_dir(backup)
        for entry in plan["account_directories"]:
            source = Path(entry["source"])
            destination = backup / entry["destination"]
            if destination.is_dir() and not source.exists():
                continue
            if source.is_symlink() or (source.exists() and not source.is_dir()):
                raise CodexSharedStateError(f"unsafe Codex state path: {source}")
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.replace(source, destination)
        plan["phase"] = phase = "install"
        _write_private_json(stage / "plan.json", plan)

    if phase == "install":
        for directory in ("sessions", "archived_sessions"):
            source = canonical_stage / directory
            destination = root / directory
            if destination.is_dir() and not source.exists():
                continue
            if destination.exists():
                raise CodexSharedStateError(
                    f"canonical Codex state already exists unexpectedly: {destination}"
                )
            source.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(source, destination)
        for raw_home in plan["accounts"]:
            prepare_codex_account_projection(root, raw_home)
        plan["phase"] = "complete"
        _write_private_json(stage / "plan.json", plan)

    if plan.get("phase") != "complete":
        raise CodexSharedStateError(f"unknown Codex migration phase: {plan.get('phase')}")

    marker_payload = {
        key: value
        for key, value in plan.items()
        if key not in {"phase", "moves", "account_directories"}
    }
    _write_private_json(root / "migration.json", marker_payload)
    shutil.rmtree(stage)


def _goal_rows(
    account_homes: Iterable[Path],
    goal_bindings: Mapping[str, Path] | None = None,
) -> tuple[list[str], dict[str, tuple], set[str]]:
    expected_columns: list[str] | None = None
    candidates: dict[str, list[tuple[Path, tuple, bool]]] = {}
    for home in account_homes:
        path = home / "goals_1.sqlite"
        if not path.is_file() or path.is_symlink():
            continue
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            columns = [row[1] for row in connection.execute("pragma table_info(thread_goals)")]
            if not columns:
                continue
            if expected_columns is None:
                expected_columns = columns
            elif columns != expected_columns:
                raise CodexSharedStateError("Codex Goal schemas differ across accounts")
            updated_index = columns.index("updated_at_ms")
            thread_index = columns.index("thread_id")
            has_deferral_table = bool(connection.execute(
                "select 1 from sqlite_master where type='table' and "
                "name='thread_goal_continuation_deferrals'"
            ).fetchone())
            for row in connection.execute("select * from thread_goals"):
                thread_id = str(row[thread_index])
                deferred = bool(
                    has_deferral_table
                    and connection.execute(
                        "select 1 from thread_goal_continuation_deferrals "
                        "where thread_id=?",
                        (thread_id,),
                    ).fetchone()
                )
                candidates.setdefault(thread_id, []).append(
                    (home, tuple(row), deferred)
                )
        finally:
            connection.close()
    winners: dict[str, tuple] = {}
    deferred_winners: set[str] = set()
    for thread_id, rows in candidates.items():
        bound_home = (goal_bindings or {}).get(thread_id.lower())
        bound = [row for row in rows if row[0] == bound_home]
        chosen = (
            bound[0]
            if len(bound) == 1
            else max(rows, key=lambda row: int(row[1][updated_index]))
        )
        winners[thread_id] = chosen[1]
        if chosen[2]:
            deferred_winners.add(thread_id)
    return expected_columns or [], winners, deferred_winners


def _write_goal_database(
    root: Path,
    account_homes: list[Path],
    goal_bindings: Mapping[str, Path] | None = None,
) -> None:
    columns, winners, deferred_winners = _goal_rows(
        account_homes,
        goal_bindings,
    )
    if not columns:
        return
    source = next(
        home / "goals_1.sqlite"
        for home in account_homes
        if (home / "goals_1.sqlite").is_file()
    )
    fd, raw_temporary = tempfile.mkstemp(prefix=".goals-", suffix=".sqlite", dir=root)
    os.close(fd)
    temporary = Path(raw_temporary)
    try:
        source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        target_db = sqlite3.connect(temporary)
        try:
            source_db.backup(target_db)
            target_db.execute(
                "create table if not exists "
                "thread_goal_continuation_deferrals ("
                "thread_id text primary key not null references "
                "thread_goals(thread_id) on delete cascade)"
            )
            target_db.execute("delete from thread_goal_continuation_deferrals")
            target_db.execute("delete from thread_goals")
            placeholders = ",".join("?" for _ in columns)
            quoted = ",".join(f'"{column}"' for column in columns)
            target_db.executemany(
                f"insert into thread_goals ({quoted}) values ({placeholders})",
                list(winners.values()),
            )
            target_db.executemany(
                "insert into thread_goal_continuation_deferrals (thread_id) "
                "values (?)",
                [(thread_id,) for thread_id in sorted(deferred_winners)],
            )
            target_db.commit()
        finally:
            source_db.close()
            target_db.close()
        os.chmod(temporary, 0o600)
        os.replace(temporary, root / "goals_1.sqlite")
    finally:
        temporary.unlink(missing_ok=True)


def _project_directory(shared: Path, account_home: Path, name: str) -> None:
    destination = account_home / name
    target = shared / name
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target, 0o700)
    if destination.is_symlink():
        if destination.resolve(strict=False) != target.resolve(strict=False):
            raise CodexSharedStateError(f"Codex state symlink points elsewhere: {destination}")
        return
    if destination.exists():
        if not destination.is_dir():
            raise CodexSharedStateError(f"unsafe Codex state path: {destination}")
        if any(destination.iterdir()):
            raise CodexSharedStateError(f"unmigrated non-empty Codex state directory: {destination}")
        destination.rmdir()
    temporary = account_home / f".{name}.ccm-link-{os.getpid()}"
    temporary.unlink(missing_ok=True)
    os.symlink(target, temporary, target_is_directory=True)
    os.replace(temporary, destination)


def prepare_codex_account_projection(
    shared_root: str | os.PathLike[str],
    account_home: str | os.PathLike[str],
) -> None:
    root = _private_dir(Path(shared_root).expanduser())
    home = _private_dir(Path(account_home).expanduser())
    for name in ("sessions", "archived_sessions"):
        _project_directory(root, home, name)


def converge_codex_shared_state(
    shared_root: str | os.PathLike[str],
    account_homes: Iterable[str | os.PathLike[str]],
    *,
    task_bindings: Mapping[str, str | os.PathLike[str]] | None = None,
    goal_bindings: Mapping[str, str | os.PathLike[str]] | None = None,
) -> dict:
    """Converge legacy per-account rollout/Goal state into one private root."""

    root = _private_dir(Path(shared_root).expanduser())
    homes = [_private_dir(Path(home).expanduser()) for home in account_homes]
    marker = root / "migration.json"
    if marker.is_file():
        for home in homes:
            prepare_codex_account_projection(root, home)
        for stale_stage in root.glob(".migration-stage-*"):
            if stale_stage.is_dir() and not stale_stage.is_symlink():
                shutil.rmtree(stale_stage)
        return {"migrated": False, **json.loads(marker.read_text())}

    stages = [
        path for path in root.glob(".migration-stage-*")
        if path.is_dir() and not path.is_symlink()
    ]
    if len(stages) > 1:
        raise CodexSharedStateError("multiple incomplete Codex migrations found")
    if stages:
        stage = stages[0]
        plan_path = stage / "plan.json"
        if not plan_path.is_file() or plan_path.is_symlink():
            raise CodexSharedStateError("incomplete Codex migration has no safe plan")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        _resume_rollout_migration(root, stage, plan)
        return {"migrated": True, **json.loads(marker.read_text())}

    migration_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_relative = str(Path("legacy") / migration_id)
    bound = {
        thread.lower(): Path(home).expanduser().resolve(strict=False)
        for thread, home in (task_bindings or {}).items()
    }
    bound_goals = {
        thread.lower(): Path(home).expanduser().resolve(strict=False)
        for thread, home in (goal_bindings or {}).items()
    }
    grouped: dict[tuple[str, str], list[tuple[Path, Path]]] = {}
    for home in homes:
        for directory in ("sessions", "archived_sessions"):
            for path in _rollouts(home, directory):
                grouped.setdefault((directory, _thread_id(path)), []).append((home, path))

    diverged: list[str] = []
    moves: list[dict[str, str]] = []
    for (directory, thread), candidates in grouped.items():
        winner_home, winner, conflict = _choose_rollout(candidates, bound.get(thread))
        if conflict:
            diverged.append(thread)
        relative = winner.relative_to(winner_home / directory)
        moves.append({
            "source": str(winner),
            "destination": str(Path(directory) / relative),
        })

    _write_goal_database(root, homes, bound_goals)
    account_directories = []
    for index, home in enumerate(homes):
        backup_name = f"{index:03d}-{home.name}"
        for directory in ("sessions", "archived_sessions"):
            account_directories.append({
                "source": str(home / directory),
                "destination": str(Path(backup_name) / directory),
            })

    plan = {
        "version": 1,
        "created_at": int(time.time()),
        "backup_relative": backup_relative,
        "diverged_threads": sorted(set(diverged)),
        "accounts": [str(home) for home in homes],
        "goal_overrides": {
            thread: str(home) for thread, home in sorted(bound_goals.items())
        },
        "phase": "staging",
        "moves": moves,
        "account_directories": account_directories,
    }
    stage = _private_dir(root / f".migration-stage-{migration_id}")
    _write_private_json(stage / "plan.json", plan)
    _resume_rollout_migration(root, stage, plan)
    return {"migrated": True, **json.loads(marker.read_text())}


__all__ = [
    "CodexSharedStateError",
    "converge_codex_shared_state",
    "prepare_codex_account_projection",
]
