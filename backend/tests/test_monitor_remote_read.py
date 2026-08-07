"""Security and command-template tests for Monitor remote reads."""

import asyncio

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.monitor_remote_read import (
    MonitorRemoteReadError,
    build_remote_read_command,
    execute_monitor_remote_read,
    parse_monitor_ssh_profiles,
)


def _profiles_json() -> str:
    return r'''{
      "yc_h100": {
        "host": "121.46.19.4",
        "port": 8001,
        "user": "cluster_user",
        "key_path": "/srv/ccm-secrets/yc_h100.key",
        "known_hosts_path": "/srv/ccm-secrets/known_hosts",
        "allowed_roots": ["/home/cluster_user", "/data/jobs"]
      }
    }'''


def test_parse_profile_keeps_transport_and_roots_server_owned():
    profiles = parse_monitor_ssh_profiles(_profiles_json())

    profile = profiles["yc_h100"]
    assert profile.host == "121.46.19.4"
    assert profile.port == 8001
    assert profile.user == "cluster_user"
    assert profile.allowed_roots == (
        "/home/cluster_user",
        "/data/jobs",
    )


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"bad name": {}}',
        '{"x":{"host":"host; reboot","user":"u","key_path":"/k","known_hosts_path":"/h"}}',
        '{"x":{"host":"h","port":70000,"user":"u","key_path":"/k","known_hosts_path":"/h"}}',
        '{"x":{"host":"h","user":"u","key_path":"relative","known_hosts_path":"/h"}}',
        '{"x":{"host":"h","user":"u","key_path":"/k","known_hosts_path":"/h","allowed_roots":["../escape"]}}',
    ],
)
def test_parse_profile_rejects_unsafe_configuration(raw):
    with pytest.raises(MonitorRemoteReadError) as exc_info:
        parse_monitor_ssh_profiles(raw)

    assert exc_info.value.permanent is True


def test_log_tail_uses_remote_realpath_guard():
    profile = parse_monitor_ssh_profiles(_profiles_json())["yc_h100"]

    command = build_remote_read_command(
        profile,
        operation="log_tail",
        path="/data/jobs/run-1/output.log",
        lines=120,
    )

    assert "realpath" in command
    assert "/data/jobs" in command
    assert "tail -n 120" in command


@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [
        ("log_tail", {"path": "/data/jobs/../../etc/shadow"}),
        ("log_tail", {"path": "/data/jobs/x; touch /tmp/pwned"}),
        ("slurm_job", {"job_id": "12; scancel 12"}),
        ("tmux_pane", {"tmux_session": "x; send-keys reboot"}),
        ("unknown", {}),
    ],
)
def test_command_builder_rejects_injection_and_unsupported_operations(
    operation,
    kwargs,
):
    profile = parse_monitor_ssh_profiles(_profiles_json())["yc_h100"]

    with pytest.raises(MonitorRemoteReadError):
        build_remote_read_command(profile, operation=operation, **kwargs)


async def test_execute_uses_strict_profile_and_bounded_read():
    fake_executor = AsyncMock()
    fake_executor.run.return_value = (0, "gpu ok")

    with patch(
        "backend.services.monitor_remote_read.SSHExecutor",
        return_value=fake_executor,
    ) as executor_cls:
        result = await execute_monitor_remote_read(
            raw_profiles=_profiles_json(),
            profile_name="yc_h100",
            operation="gpu_status",
        )

    executor_cls.assert_called_once_with(
        "121.46.19.4",
        "cluster_user",
        "/srv/ccm-secrets/yc_h100.key",
        port=8001,
        known_hosts_path="/srv/ccm-secrets/known_hosts",
        strict_host_key_checking=True,
    )
    fake_executor.run.assert_awaited_once()
    assert fake_executor.run.await_args.kwargs == {
        "timeout": 20,
        "sensitive": True,
        "max_output_bytes": 128 * 1024,
    }
    assert result.exit_code == 0
    assert result.output == "gpu ok"


async def test_missing_profile_is_a_permanent_capability_failure():
    with pytest.raises(MonitorRemoteReadError) as exc_info:
        await execute_monitor_remote_read(
            raw_profiles=_profiles_json(),
            profile_name="not-configured",
            operation="connection",
        )

    assert exc_info.value.code == "profile_not_found"
    assert exc_info.value.permanent is True


async def test_remote_read_does_not_swallow_cancellation():
    fake_executor = AsyncMock()
    fake_executor.run.side_effect = asyncio.CancelledError()

    with patch(
        "backend.services.monitor_remote_read.SSHExecutor",
        return_value=fake_executor,
    ):
        with pytest.raises(asyncio.CancelledError):
            await execute_monitor_remote_read(
                raw_profiles=_profiles_json(),
                profile_name="yc_h100",
                operation="connection",
            )
