"""Unit tests for NsjailBackend.

These tests do NOT require nsjail to be installed – they mock subprocess
calls and filesystem checks to verify argument construction, session
directory management, and cgroup detection logic.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from unittest import mock

import pytest

from langbot_plugin.box.nsjail_backend import (
    NsjailBackend,
    _READONLY_ETC_ENTRIES,
    _READONLY_SYSTEM_MOUNTS,
)
from langbot_plugin.box.models import (
    BoxExecutionStatus,
    BoxHostMountMode,
    BoxNetworkMode,
    BoxSessionInfo,
    BoxSpec,
)


@pytest.fixture
def logger():
    return logging.getLogger('test.nsjail')


@pytest.fixture
def tmp_base(tmp_path: pathlib.Path):
    return tmp_path / 'nsjail-base'


@pytest.fixture
def backend(logger, tmp_base):
    b = NsjailBackend(logger=logger, base_dir=str(tmp_base))
    b.instance_id = 'test123'
    return b


# ── is_available ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_is_available_no_binary(backend):
    with mock.patch('shutil.which', return_value=None):
        assert await backend.is_available() is False


@pytest.mark.anyio
async def test_is_available_binary_exists(backend, tmp_base):
    with (
        mock.patch('shutil.which', return_value='/usr/bin/nsjail'),
        mock.patch('asyncio.create_subprocess_exec') as mock_exec,
    ):
        mock_proc = mock.AsyncMock()
        mock_proc.returncode = 0
        mock_proc.wait = mock.AsyncMock(return_value=0)
        mock_exec.return_value = mock_proc

        result = await backend.is_available()
        assert result is True
        assert tmp_base.exists()


# ── start_session ─────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_start_session_creates_directories(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    spec = BoxSpec(session_id='sess1', cmd='echo hi')

    info = await backend.start_session(spec)

    session_dir = pathlib.Path(info.backend_session_id)
    assert session_dir.exists()
    assert (session_dir / 'workspace').is_dir()
    assert (session_dir / 'tmp').is_dir()
    assert (session_dir / 'home').is_dir()
    assert (session_dir / 'meta.json').exists()

    assert info.backend_name == 'nsjail'
    assert info.session_id == 'sess1'
    assert info.image == 'host'
    assert info.read_only_rootfs is True


@pytest.mark.anyio
async def test_start_session_with_host_path(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    spec = BoxSpec(
        session_id='sess2',
        cmd='ls',
        host_path='/some/path',
        host_path_mode=BoxHostMountMode.READ_WRITE,
        mount_path='/project',
    )

    info = await backend.start_session(spec)
    assert info.host_path == '/some/path'
    assert info.host_path_mode == BoxHostMountMode.READ_WRITE
    assert info.mount_path == '/project'


# ── stop_session ──────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_stop_session_removes_directory(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    spec = BoxSpec(session_id='sess-rm', cmd='echo')

    info = await backend.start_session(spec)
    session_dir = pathlib.Path(info.backend_session_id)
    assert session_dir.exists()

    await backend.stop_session(info)
    assert not session_dir.exists()


# ── nsjail argument construction ──────────────────────────────────────

def test_build_nsjail_args_basic(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    session_dir = tmp_base / 'test_session'
    for d in ('workspace', 'tmp', 'home'):
        (session_dir / d).mkdir(parents=True)

    session = BoxSessionInfo(
        session_id='s1',
        backend_name='nsjail',
        backend_session_id=str(session_dir),
        image='host',
        network=BoxNetworkMode.OFF,
        created_at='2024-01-01T00:00:00+00:00',
        last_used_at='2024-01-01T00:00:00+00:00',
    )
    spec = BoxSpec(session_id='s1', cmd='echo hello', env={'FOO': 'bar'})

    args = backend._build_nsjail_args(session, spec, session_dir)

    assert args[0] == 'nsjail'
    assert '--mode' in args
    assert args[args.index('--mode') + 1] == 'o'
    assert '--clone_newnet' in args
    assert '--disable_clone_newnet' not in args
    assert '--really_quiet' in args

    # Writable mounts should reference session directories.
    rw_binds = [args[i + 1] for i, a in enumerate(args) if a == '--rw_bind']
    workspace_mount = f'{session_dir}/workspace:/workspace'
    assert workspace_mount in rw_binds

    # Custom env should be present.
    env_values = [args[i + 1] for i, a in enumerate(args) if a == '--env']
    assert 'FOO=bar' in env_values

    # Command is the last part after '--'.
    separator_idx = args.index('--')
    assert args[separator_idx + 1] == 'sh'


def test_build_nsjail_args_network_on(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    session_dir = tmp_base / 'test_session_net'
    for d in ('workspace', 'tmp', 'home'):
        (session_dir / d).mkdir(parents=True)

    session = BoxSessionInfo(
        session_id='s2',
        backend_name='nsjail',
        backend_session_id=str(session_dir),
        image='host',
        network=BoxNetworkMode.ON,
        created_at='2024-01-01T00:00:00+00:00',
        last_used_at='2024-01-01T00:00:00+00:00',
    )
    spec = BoxSpec(session_id='s2', cmd='curl http://example.com', network=BoxNetworkMode.ON)

    args = backend._build_nsjail_args(session, spec, session_dir)

    assert '--disable_clone_newnet' in args
    assert '--clone_newnet' not in args


def test_build_nsjail_args_host_path_ro(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    session_dir = tmp_base / 'test_hp'
    for d in ('workspace', 'tmp', 'home'):
        (session_dir / d).mkdir(parents=True)

    session = BoxSessionInfo(
        session_id='s3',
        backend_name='nsjail',
        backend_session_id=str(session_dir),
        image='host',
        network=BoxNetworkMode.OFF,
        host_path='/data/project',
        host_path_mode=BoxHostMountMode.READ_ONLY,
        created_at='2024-01-01T00:00:00+00:00',
        last_used_at='2024-01-01T00:00:00+00:00',
    )
    spec = BoxSpec(
        session_id='s3',
        cmd='ls',
        host_path='/data/project',
        host_path_mode=BoxHostMountMode.READ_ONLY,
    )

    args = backend._build_nsjail_args(session, spec, session_dir)

    ro_binds = [args[i + 1] for i, a in enumerate(args) if a == '--bindmount_ro']
    assert '/data/project:/workspace' in ro_binds


def test_build_nsjail_args_uses_custom_mount_path(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    session_dir = tmp_base / 'test_custom_mount'
    for d in ('workspace', 'tmp', 'home'):
        (session_dir / d).mkdir(parents=True)

    session = BoxSessionInfo(
        session_id='s4',
        backend_name='nsjail',
        backend_session_id=str(session_dir),
        image='host',
        network=BoxNetworkMode.OFF,
        host_path='/data/project',
        host_path_mode=BoxHostMountMode.READ_WRITE,
        mount_path='/project',
        created_at='2024-01-01T00:00:00+00:00',
        last_used_at='2024-01-01T00:00:00+00:00',
    )
    spec = BoxSpec(
        session_id='s4',
        cmd='pwd',
        workdir='/project/src',
        host_path='/data/project',
        host_path_mode=BoxHostMountMode.READ_WRITE,
        mount_path='/project',
    )

    args = backend._build_nsjail_args(session, spec, session_dir)

    rw_binds = [args[i + 1] for i, a in enumerate(args) if a == '--rw_bind']
    assert '/data/project:/project' in rw_binds
    assert args[args.index('--cwd') + 1] == '/project/src'


def test_build_resource_limits_cgroup(backend):
    backend._cgroup_v2_available = True
    spec = BoxSpec(session_id='s', cmd='x', cpus=2.0, memory_mb=1024, pids_limit=256)

    args = backend._build_resource_limits(spec)

    assert '--cgroup_mem_max' in args
    mem_idx = args.index('--cgroup_mem_max')
    assert args[mem_idx + 1] == str(1024 * 1024 * 1024)

    pids_idx = args.index('--cgroup_pids_max')
    assert args[pids_idx + 1] == '256'

    cpu_idx = args.index('--cgroup_cpu_ms_per_sec')
    assert args[cpu_idx + 1] == '2000'


def test_build_resource_limits_rlimit_fallback(backend):
    backend._cgroup_v2_available = False
    spec = BoxSpec(session_id='s', cmd='x', memory_mb=512, pids_limit=128)

    args = backend._build_resource_limits(spec)

    assert '--rlimit_as' in args
    as_idx = args.index('--rlimit_as')
    assert args[as_idx + 1] == '512'

    nproc_idx = args.index('--rlimit_nproc')
    assert args[nproc_idx + 1] == '128'

    # cgroup flags should NOT be present.
    assert '--cgroup_mem_max' not in args


# ── exec ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_exec_success(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    spec = BoxSpec(session_id='exec1', cmd='echo hello')
    info = await backend.start_session(spec)

    with mock.patch.object(backend, '_run_nsjail') as mock_run:
        from langbot_plugin.box.backend import _CommandResult
        mock_run.return_value = _CommandResult(
            return_code=0, stdout='hello\n', stderr='', timed_out=False
        )

        result = await backend.exec(info, spec)

    assert result.status == BoxExecutionStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == 'hello\n'
    assert result.backend_name == 'nsjail'


@pytest.mark.anyio
async def test_exec_timeout(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    spec = BoxSpec(session_id='exec2', cmd='sleep 100', timeout_sec=1)
    info = await backend.start_session(spec)

    with mock.patch.object(backend, '_run_nsjail') as mock_run:
        from langbot_plugin.box.backend import _CommandResult
        mock_run.return_value = _CommandResult(
            return_code=-1, stdout='', stderr='', timed_out=True
        )

        result = await backend.exec(info, spec)

    assert result.status == BoxExecutionStatus.TIMED_OUT
    assert result.exit_code is None


# ── cgroup detection ──────────────────────────────────────────────────

def test_detect_cgroup_v2_no_mount():
    with mock.patch.object(pathlib.Path, 'exists', return_value=False):
        assert NsjailBackend._detect_cgroup_v2() is False


def test_detect_cgroup_v2_root_user():
    orig_exists = pathlib.Path.exists

    def always_exists(self):
        return True

    with (
        mock.patch('os.getuid', return_value=0),
        mock.patch.object(pathlib.Path, 'exists', always_exists),
    ):
        assert NsjailBackend._detect_cgroup_v2() is True


# ── cleanup_orphaned_containers ───────────────────────────────────────

@pytest.mark.anyio
async def test_cleanup_orphaned_removes_old_sessions(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)

    # Create a dir from a different instance.
    old_dir = tmp_base / 'oldinst_sess1_abc'
    old_dir.mkdir()
    (old_dir / 'workspace').mkdir()

    # Create a dir from current instance.
    current_dir = tmp_base / 'test123_sess2_def'
    current_dir.mkdir()
    (current_dir / 'workspace').mkdir()

    with mock.patch.object(backend, '_kill_session_processes', new_callable=mock.AsyncMock):
        await backend.cleanup_orphaned_containers('test123')

    assert not old_dir.exists()
    assert current_dir.exists()


# ── output clipping ──────────────────────────────────────────────────

def test_clip_captured_bytes_within_limit():
    data = b'hello world'
    result = NsjailBackend._clip_captured_bytes(data, len(data))
    assert result == 'hello world'


def test_clip_captured_bytes_exceeds_limit():
    data = b'hello'
    result = NsjailBackend._clip_captured_bytes(data, 2_000_000, limit=1_000_000)
    assert 'clipped' in result
    assert '1000000' in result
