"""Structured read-only SSH operations for CCM Monitor.

The agent selects only a configured profile name and a small operation. Host,
port, user, credentials and command templates remain server-owned.
"""

from __future__ import annotations

import json
import posixpath
import re
import socket
from dataclasses import dataclass

import paramiko

from backend.services.ssh_executor import (
    SSHExecutor,
    SSHKeyPreflightError,
    SSHOutputLimitError,
)


_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$")
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_JOB_ID_RE = re.compile(r"^[0-9]{1,32}$")
_TMUX_TARGET_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_MAX_OUTPUT_BYTES = 128 * 1024
_REMOTE_TIMEOUT_SECONDS = 20


class MonitorRemoteReadError(RuntimeError):
    """Stable remote-read error safe to return to an agent."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        permanent: bool = False,
    ):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.permanent = permanent


@dataclass(frozen=True, slots=True)
class MonitorSSHProfile:
    host: str
    port: int
    user: str
    key_path: str
    known_hosts_path: str
    allowed_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MonitorRemoteReadResult:
    profile: str
    operation: str
    exit_code: int
    output: str


def _absolute_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise MonitorRemoteReadError(
            "invalid_profile",
            f"Monitor SSH {field} must be a non-empty path",
            permanent=True,
        )
    normalized = posixpath.normpath(value)
    if not normalized.startswith("/"):
        raise MonitorRemoteReadError(
            "invalid_profile",
            f"Monitor SSH {field} must be absolute",
            permanent=True,
        )
    return normalized


def parse_monitor_ssh_profiles(
    raw_profiles: str,
) -> dict[str, MonitorSSHProfile]:
    """Parse the deployment-owned profile map with strict validation."""

    if not raw_profiles or not raw_profiles.strip():
        return {}
    try:
        payload = json.loads(raw_profiles)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MonitorRemoteReadError(
            "invalid_profile_config",
            "Monitor SSH profile configuration is not valid JSON",
            permanent=True,
        ) from exc
    if not isinstance(payload, dict):
        raise MonitorRemoteReadError(
            "invalid_profile_config",
            "Monitor SSH profile configuration must be an object",
            permanent=True,
        )

    profiles: dict[str, MonitorSSHProfile] = {}
    for name, item in payload.items():
        if not isinstance(name, str) or _PROFILE_RE.fullmatch(name) is None:
            raise MonitorRemoteReadError(
                "invalid_profile",
                "Monitor SSH profile name is invalid",
                permanent=True,
            )
        if not isinstance(item, dict):
            raise MonitorRemoteReadError(
                "invalid_profile",
                f"Monitor SSH profile {name!r} must be an object",
                permanent=True,
            )
        host = item.get("host")
        user = item.get("user")
        port = item.get("port", 22)
        if not isinstance(host, str) or _HOST_RE.fullmatch(host) is None:
            raise MonitorRemoteReadError(
                "invalid_profile",
                f"Monitor SSH profile {name!r} has an invalid host",
                permanent=True,
            )
        if not isinstance(user, str) or _USER_RE.fullmatch(user) is None:
            raise MonitorRemoteReadError(
                "invalid_profile",
                f"Monitor SSH profile {name!r} has an invalid user",
                permanent=True,
            )
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise MonitorRemoteReadError(
                "invalid_profile",
                f"Monitor SSH profile {name!r} has an invalid port",
                permanent=True,
            )
        roots = item.get("allowed_roots", [])
        if not isinstance(roots, list):
            raise MonitorRemoteReadError(
                "invalid_profile",
                f"Monitor SSH profile {name!r} allowed_roots must be a list",
                permanent=True,
            )
        allowed_roots = tuple(
            _absolute_path(root, "allowed root") for root in roots
        )
        if "/" in allowed_roots:
            raise MonitorRemoteReadError(
                "invalid_profile",
                "Monitor SSH allowed root may not be the filesystem root",
                permanent=True,
            )
        profiles[name] = MonitorSSHProfile(
            host=host,
            port=port,
            user=user,
            key_path=_absolute_path(item.get("key_path"), "key path"),
            known_hosts_path=_absolute_path(
                item.get("known_hosts_path"),
                "known_hosts path",
            ),
            allowed_roots=allowed_roots,
        )
    return profiles


def _quote_shell(value: str) -> str:
    """Single-quote one already validated value for a POSIX remote shell."""

    return "'" + value.replace("'", "'\"'\"'") + "'"


def _validated_lines(lines: int) -> int:
    if isinstance(lines, bool) or not isinstance(lines, int) or not 1 <= lines <= 500:
        raise MonitorRemoteReadError(
            "invalid_argument",
            "lines must be an integer between 1 and 500",
        )
    return lines


def _guarded_remote_path(
    profile: MonitorSSHProfile,
    path: str | None,
) -> str:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise MonitorRemoteReadError(
            "invalid_argument",
            "A non-empty absolute path is required",
        )
    if re.search(r"[\r\n;&|`$<>\\'\"]", path):
        raise MonitorRemoteReadError(
            "path_not_allowed",
            "Remote path contains unsupported shell metacharacters",
        )
    normalized = posixpath.normpath(path)
    if not normalized.startswith("/") or normalized != path.rstrip("/"):
        raise MonitorRemoteReadError(
            "path_not_allowed",
            "Remote path must be normalized and absolute",
        )
    if not profile.allowed_roots:
        raise MonitorRemoteReadError(
            "path_reads_disabled",
            "This Monitor SSH profile does not allow path reads",
        )
    if not any(
        normalized == root or normalized.startswith(root + "/")
        for root in profile.allowed_roots
    ):
        raise MonitorRemoteReadError(
            "path_not_allowed",
            "Remote path is outside the configured read roots",
        )

    patterns = "|".join(
        f"{_quote_shell(root)}|{_quote_shell(root)}/*"
        for root in profile.allowed_roots
    )
    return (
        f"target=$(realpath -e -- {_quote_shell(normalized)}) || exit 66; "
        f"case \"$target\" in {patterns}) ;; *) "
        "echo 'resolved path is outside allowed roots' >&2; exit 77;; esac; "
    )


def build_remote_read_command(
    profile: MonitorSSHProfile,
    *,
    operation: str,
    path: str | None = None,
    job_id: str | None = None,
    tmux_session: str | None = None,
    lines: int = 100,
) -> str:
    """Return one fixed read-only command for a validated operation."""

    lines = _validated_lines(lines)
    commands = {
        "connection": (
            "printf 'hostname: '; hostname; printf 'uptime: '; uptime"
        ),
        "process_status": (
            "ps -eo pid,ppid,stat,etime,%cpu,%mem,args --sort=-%cpu "
            "| head -n 81"
        ),
        "gpu_status": (
            "nvidia-smi --query-gpu=index,name,temperature.gpu,"
            "utilization.gpu,memory.used,memory.total "
            "--format=csv,noheader,nounits"
        ),
        "slurm_queue": (
            "squeue -u \"$USER\" -o '%.18i %.12P %.30j %.8T %.10M %.6D %R'"
        ),
        "tmux_sessions": "tmux list-sessions",
    }
    if operation in commands:
        return "LC_ALL=C " + commands[operation]
    if operation == "slurm_job":
        if not isinstance(job_id, str) or _JOB_ID_RE.fullmatch(job_id) is None:
            raise MonitorRemoteReadError(
                "invalid_argument",
                "job_id must contain digits only",
            )
        return (
            "LC_ALL=C "
            f"squeue -j {_quote_shell(job_id)} -o "
            "'%.18i %.12P %.30j %.8T %.10M %.6D %R'; "
            f"sacct -j {_quote_shell(job_id)} -n -P "
            "--format=JobID,JobName,Partition,State,Elapsed,ExitCode"
        )
    if operation in {"log_tail", "file_stat"}:
        guard = _guarded_remote_path(profile, path)
        if operation == "log_tail":
            return (
                "LC_ALL=C " + guard + f"tail -n {lines} -- \"$target\""
            )
        return (
            "LC_ALL=C " + guard
            + "stat -c '%F|%s|%y|%a|%U:%G|%n' -- \"$target\""
        )
    if operation == "tmux_pane":
        if (
            not isinstance(tmux_session, str)
            or _TMUX_TARGET_RE.fullmatch(tmux_session) is None
        ):
            raise MonitorRemoteReadError(
                "invalid_argument",
                "tmux_session contains unsupported characters",
            )
        return (
            "LC_ALL=C tmux capture-pane -p -t "
            f"{_quote_shell(tmux_session)} -S -{lines}"
        )
    raise MonitorRemoteReadError(
        "operation_not_allowed",
        "Requested remote-read operation is not allowed",
    )


def _translate_transport_error(exc: BaseException) -> MonitorRemoteReadError:
    if isinstance(exc, SSHKeyPreflightError):
        return MonitorRemoteReadError(exc.code, exc.detail, permanent=True)
    if isinstance(exc, paramiko.BadHostKeyException):
        return MonitorRemoteReadError(
            "host_key_mismatch",
            "SSH host key does not match the trusted key",
            permanent=True,
        )
    if isinstance(exc, paramiko.AuthenticationException):
        return MonitorRemoteReadError(
            "authentication_failed",
            "SSH rejected the configured user/private key",
            permanent=True,
        )
    if isinstance(exc, SSHOutputLimitError):
        return MonitorRemoteReadError(
            "output_limit",
            "Remote status output exceeded the safe limit",
        )
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return MonitorRemoteReadError(
            "connection_timeout",
            "Remote status connection or command timed out",
        )
    if isinstance(exc, (paramiko.SSHException, OSError)):
        return MonitorRemoteReadError(
            "connection_failed",
            "Remote status SSH connection failed",
        )
    return MonitorRemoteReadError(
        "remote_read_failed",
        "Remote status read failed unexpectedly",
    )


async def execute_monitor_remote_read(
    *,
    raw_profiles: str,
    profile_name: str,
    operation: str,
    path: str | None = None,
    job_id: str | None = None,
    tmux_session: str | None = None,
    lines: int = 100,
) -> MonitorRemoteReadResult:
    profiles = parse_monitor_ssh_profiles(raw_profiles)
    profile = profiles.get(profile_name)
    if profile is None:
        raise MonitorRemoteReadError(
            "profile_not_found",
            "Requested Monitor SSH profile is not configured",
            permanent=True,
        )
    command = build_remote_read_command(
        profile,
        operation=operation,
        path=path,
        job_id=job_id,
        tmux_session=tmux_session,
        lines=lines,
    )
    executor = SSHExecutor(
        profile.host,
        profile.user,
        profile.key_path,
        port=profile.port,
        known_hosts_path=profile.known_hosts_path,
        strict_host_key_checking=True,
    )
    try:
        exit_code, output = await executor.run(
            command,
            timeout=_REMOTE_TIMEOUT_SECONDS,
            sensitive=True,
            max_output_bytes=_MAX_OUTPUT_BYTES,
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise _translate_transport_error(exc) from exc
    return MonitorRemoteReadResult(
        profile=profile_name,
        operation=operation,
        exit_code=exit_code,
        output=output,
    )
