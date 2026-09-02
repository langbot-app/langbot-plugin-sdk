from __future__ import annotations

import asyncio
import logging
import os

import pytest

from langbot_plugin.box.host_backend import HostProcessBackend
from langbot_plugin.box.models import (
    BoxExecutionStatus,
    BoxManagedProcessSpec,
    BoxMountSpec,
    BoxSpec,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="host backend is POSIX-only")


@pytest.fixture
def backend() -> HostProcessBackend:
    return HostProcessBackend(logging.getLogger("test.box.host"))


def _spec(tmp_path, *, cmd: str = "true", **changes) -> BoxSpec:
    values = {
        "session_id": "host-test",
        "cmd": cmd,
        "host_path": str(tmp_path),
        "read_only_rootfs": False,
    }
    values.update(changes)
    return BoxSpec(**values)


@pytest.mark.anyio
async def test_host_backend_exec_maps_workspace_paths(backend, tmp_path):
    spec = _spec(
        tmp_path,
        cmd="printf host-ok > /workspace/result.txt && cat /workspace/result.txt",
    )
    session = await backend.start_session(spec)
    try:
        result = await backend.exec(session, spec)
    finally:
        await backend.stop_session(session)

    assert result.status == BoxExecutionStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == "host-ok"
    assert (tmp_path / "result.txt").read_text() == "host-ok"


@pytest.mark.anyio
async def test_host_backend_preserves_exit_code_and_stderr(backend, tmp_path):
    spec = _spec(
        tmp_path,
        cmd="printf host-out; printf host-error >&2; exit 7",
    )
    session = await backend.start_session(spec)
    try:
        result = await backend.exec(session, spec)
    finally:
        await backend.stop_session(session)

    assert result.status == BoxExecutionStatus.COMPLETED
    assert result.exit_code == 7
    assert result.stdout == "host-out"
    assert result.stderr == "host-error"


@pytest.mark.anyio
async def test_host_backend_maps_extra_mounts_before_workspace(backend, tmp_path):
    workspace = tmp_path / "workspace"
    skill = tmp_path / "skill"
    workspace.mkdir()
    skill.mkdir()
    (skill / "value.txt").write_text("skill-ok")
    spec = _spec(
        workspace,
        cmd="cat /workspace/.skills/demo/value.txt",
        extra_mounts=[
            BoxMountSpec(
                host_path=str(skill),
                mount_path="/workspace/.skills/demo",
                mode="ro",
            )
        ],
    )
    session = await backend.start_session(spec)
    try:
        result = await backend.exec(session, spec)
    finally:
        await backend.stop_session(session)

    assert result.exit_code == 0
    assert result.stdout == "skill-ok"


@pytest.mark.anyio
async def test_host_backend_uses_minimal_environment(backend, tmp_path, monkeypatch):
    monkeypatch.setenv("LANGBOT_BOX_CONTROL_TOKEN", "must-not-leak")
    spec = _spec(
        tmp_path,
        cmd='[ -z "${LANGBOT_BOX_CONTROL_TOKEN+x}" ] && printf %s "$VISIBLE"',
        env={"VISIBLE": "provided"},
    )
    session = await backend.start_session(spec)
    try:
        result = await backend.exec(session, spec)
    finally:
        await backend.stop_session(session)

    assert result.exit_code == 0
    assert result.stdout == "provided"


@pytest.mark.anyio
async def test_host_backend_timeout_kills_process_group(backend, tmp_path):
    spec = _spec(
        tmp_path,
        cmd="sh -c 'sleep 30 & child=$!; printf %s \"$child\" > child.pid; wait'",
        timeout_sec=1,
    )
    session = await backend.start_session(spec)
    try:
        result = await backend.exec(session, spec)
        child_pid = int((tmp_path / "child.pid").read_text())
        for _ in range(20):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("timed-out host command left a child process running")
    finally:
        await backend.stop_session(session)

    assert result.status == BoxExecutionStatus.TIMED_OUT
    assert result.exit_code is None


@pytest.mark.anyio
async def test_host_backend_cancellation_kills_process_group(backend, tmp_path):
    spec = _spec(
        tmp_path,
        cmd="sh -c 'sleep 30 & child=$!; printf %s \"$child\" > child.pid; wait'",
    )
    session = await backend.start_session(spec)
    task = asyncio.create_task(backend.exec(session, spec))
    try:
        for _ in range(100):
            if (tmp_path / "child.pid").exists():
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("host command did not start its child process")

        child_pid = int((tmp_path / "child.pid").read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        for _ in range(20):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("cancelled host command left a child process running")
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await backend.stop_session(session)


@pytest.mark.anyio
async def test_host_backend_managed_process_maps_cwd_and_args(backend, tmp_path):
    spec = _spec(tmp_path)
    session = await backend.start_session(spec)
    try:
        process = await backend.start_managed_process(
            session,
            BoxManagedProcessSpec(
                command="sh",
                args=["-c", "pwd; printf managed-ok > /workspace/managed.txt"],
                cwd="/workspace",
            ),
        )
        stdout = await process.stdout.read()
        assert await process.wait() == 0
    finally:
        await backend.stop_session(session)

    assert stdout.decode().strip() == str(tmp_path)
    assert (tmp_path / "managed.txt").read_text() == "managed-ok"


@pytest.mark.anyio
async def test_host_backend_reports_no_isolation(backend):
    readiness = await backend.get_readiness(strict=True)

    assert readiness["available"] is True
    assert readiness["unsafe_direct_execution"] is True
    assert readiness["namespace_isolation"] is False
    assert readiness["mount_isolation"] is False
    assert readiness["network_isolation"] is False
    assert readiness["cgroup_v2"] is False
