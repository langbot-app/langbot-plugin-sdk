"""Unit tests for NsjailBackend.

These tests do NOT require nsjail to be installed – they mock subprocess
calls and filesystem checks to verify argument construction, session
directory management, and cgroup detection logic.
"""

from __future__ import annotations

import logging
import pathlib
from unittest import mock

import pytest

from langbot_plugin.box.nsjail_backend import (
    NsjailBackend,
)
from langbot_plugin.box.models import (
    BoxExecutionStatus,
    BoxHostMountMode,
    BoxMountSpec,
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
    assert (session_dir / 'root').is_dir()
    assert (session_dir / 'workspace').is_dir()
    assert (session_dir / 'tmp').is_dir()
    assert (session_dir / 'home').is_dir()
    assert (session_dir / 'meta.json').exists()

    assert info.backend_name == 'nsjail'
    assert info.session_id == 'sess1'
    assert info.image == spec.image
    assert info.read_only_rootfs is True


@pytest.mark.anyio
async def test_start_session_with_host_path(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    host_path = str(tmp_base / "rw_host")
    spec = BoxSpec(
        session_id="sess2",
        cmd="ls",
        host_path=host_path,
        host_path_mode=BoxHostMountMode.READ_WRITE,
        mount_path='/project',
    )

    info = await backend.start_session(spec)
    assert info.host_path == host_path
    assert info.host_path_mode == BoxHostMountMode.READ_WRITE
    assert info.mount_path == '/project'


@pytest.mark.anyio
async def test_start_session_creates_missing_rw_host_path(backend, tmp_base):
    """Regression: a read-write host_path that does not yet exist must be
    created by start_session, otherwise nsjail's --bindmount source is missing
    and the command exits 255 with no output (SaaS MCP shared-workspace bug)."""
    tmp_base.mkdir(parents=True, exist_ok=True)
    host_path = tmp_base / "never_created" / "workspace"
    assert not host_path.exists()

    spec = BoxSpec(
        session_id="sess-mkdir",
        cmd="ls",
        host_path=str(host_path),
        host_path_mode=BoxHostMountMode.READ_WRITE,
        mount_path="/workspace",
    )

    await backend.start_session(spec)
    assert host_path.is_dir()


@pytest.mark.anyio
async def test_start_session_does_not_create_ro_host_path(backend, tmp_base):
    """A missing read-only host_path is a caller error and must NOT be silently
    created — it should surface rather than mount an empty dir."""
    tmp_base.mkdir(parents=True, exist_ok=True)
    host_path = tmp_base / "ro_missing"
    assert not host_path.exists()

    spec = BoxSpec(
        session_id="sess-ro",
        cmd="ls",
        host_path=str(host_path),
        host_path_mode=BoxHostMountMode.READ_ONLY,
        mount_path="/project",
    )

    await backend.start_session(spec)
    assert not host_path.exists()


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
    for d in ('root', 'workspace', 'tmp', 'home'):
        (session_dir / d).mkdir(parents=True)

    spec = BoxSpec(session_id='s1', cmd='echo hello', env={'FOO': 'bar'})
    session = BoxSessionInfo(
        session_id='s1',
        backend_name='nsjail',
        backend_session_id=str(session_dir),
        image=spec.image,
        network=BoxNetworkMode.OFF,
        created_at='2024-01-01T00:00:00+00:00',
        last_used_at='2024-01-01T00:00:00+00:00',
    )

    args = backend._build_nsjail_args(session, spec, session_dir)

    assert args[0] == 'nsjail'
    assert '--mode' in args
    assert args[args.index('--mode') + 1] == 'o'
    assert '--chroot' in args
    assert args[args.index('--chroot') + 1] == str(session_dir / 'root')
    assert '--clone_newnet' not in args
    assert '--clone_newuser' not in args
    assert '--clone_newns' not in args
    assert '--disable_clone_newnet' not in args
    assert '--really_quiet' in args

    # Writable mounts should reference session directories.
    rw_binds = [args[i + 1] for i, a in enumerate(args) if a == '--bindmount']
    workspace_mount = f'{session_dir}/workspace:/workspace'
    assert workspace_mount in rw_binds

    # Custom env should be present.
    env_values = [args[i + 1] for i, a in enumerate(args) if a == '--env']
    assert 'FOO=bar' in env_values

    # Command is the last part after '--'.
    separator_idx = args.index('--')
    assert args[separator_idx + 1] == '/bin/sh'

    # Mount target directories are created under the per-session chroot root.
    assert (session_dir / 'root' / 'workspace').is_dir()
    assert (session_dir / 'root' / 'tmp').is_dir()
    assert (session_dir / 'root' / 'home').is_dir()


def test_build_nsjail_args_binds_essential_dev_nodes(backend, tmp_base):
    """/dev is a fresh empty tmpfs, so essential character devices must be
    bind-mounted in. Regression: without /dev/null, uv's glibc/musl detection
    subprocess fails ("Could not detect either glibc version nor musl libc
    version") and uvx-launched stdio MCP servers die before the initialize
    handshake, surfacing as a misleading "Connection closed / please check URL".
    """
    tmp_base.mkdir(parents=True, exist_ok=True)
    session_dir = tmp_base / "test_dev"
    for d in ("root", "workspace", "tmp", "home"):
        (session_dir / d).mkdir(parents=True)

    spec = BoxSpec(session_id="s-dev", cmd="echo hi")
    session = BoxSessionInfo(
        session_id="s-dev",
        backend_name="nsjail",
        backend_session_id=str(session_dir),
        image=spec.image,
        network=BoxNetworkMode.OFF,
        created_at="2024-01-01T00:00:00+00:00",
        last_used_at="2024-01-01T00:00:00+00:00",
    )

    # Pretend every candidate device node exists on the host.
    with mock.patch("os.path.exists", return_value=True):
        args = backend._build_nsjail_args(session, spec, session_dir)

    # /dev itself is a tmpfs mount.
    mount_specs = [args[i + 1] for i, a in enumerate(args) if a == "--mount"]
    assert "none:/dev:tmpfs:rw" in mount_specs

    # /dev/null (the critical one for uv) must be bind-mounted read-write,
    # ordered AFTER the /dev tmpfs mount so it lands on the fresh tmpfs.
    rw_binds = [args[i + 1] for i, a in enumerate(args) if a == "--bindmount"]
    assert "/dev/null:/dev/null" in rw_binds
    assert "/dev/urandom:/dev/urandom" in rw_binds

    dev_tmpfs_idx = next(
        i
        for i, a in enumerate(args)
        if a == "--mount" and args[i + 1] == "none:/dev:tmpfs:rw"
    )
    dev_null_idx = next(
        i
        for i, a in enumerate(args)
        if a == "--bindmount" and args[i + 1] == "/dev/null:/dev/null"
    )
    assert dev_tmpfs_idx < dev_null_idx


def test_build_nsjail_args_network_on(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    session_dir = tmp_base / 'test_session_net'
    for d in ('root', 'workspace', 'tmp', 'home'):
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
    for d in ('root', 'workspace', 'tmp', 'home'):
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
    for d in ('root', 'workspace', 'tmp', 'home'):
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

    rw_binds = [args[i + 1] for i, a in enumerate(args) if a == '--bindmount']
    assert '/data/project:/project' in rw_binds
    assert args[args.index('--cwd') + 1] == '/project/src'
    assert (session_dir / 'root' / 'project').is_dir()


def test_build_nsjail_args_extra_mounts_prepare_targets(backend, tmp_base):
    tmp_base.mkdir(parents=True, exist_ok=True)
    session_dir = tmp_base / 'test_extra_mount'
    for d in ('root', 'workspace', 'tmp', 'home'):
        (session_dir / d).mkdir(parents=True)

    session = BoxSessionInfo(
        session_id='s5',
        backend_name='nsjail',
        backend_session_id=str(session_dir),
        image='host',
        network=BoxNetworkMode.OFF,
        created_at='2024-01-01T00:00:00+00:00',
        last_used_at='2024-01-01T00:00:00+00:00',
    )
    spec = BoxSpec(
        session_id='s5',
        cmd='ls /workspace/.skills/demo',
        extra_mounts=[
            BoxMountSpec(
                host_path='/data/skills/demo',
                mount_path='/workspace/.skills/demo',
                mode=BoxHostMountMode.READ_WRITE,
            )
        ],
    )

    args = backend._build_nsjail_args(session, spec, session_dir)

    rw_binds = [args[i + 1] for i, a in enumerate(args) if a == '--bindmount']
    assert '/data/skills/demo:/workspace/.skills/demo' in rw_binds
    assert (session_dir / 'root' / 'workspace' / '.skills' / 'demo').is_dir()


def test_build_resource_limits_cgroup(backend):
    backend._cgroup_v2_available = True
    spec = BoxSpec(session_id='s', cmd='x', cpus=2.0, memory_mb=1024, pids_limit=256)

    args = backend._build_resource_limits(spec)

    # Bug regression: cgroup v2 mode MUST opt in explicitly, otherwise nsjail
    # falls back to the v1 layout and aborts on a v2-only host.
    assert "--use_cgroupv2" in args
    assert "--cgroup_mem_max" in args
    mem_idx = args.index("--cgroup_mem_max")
    assert args[mem_idx + 1] == str(1024 * 1024 * 1024)

    pids_idx = args.index('--cgroup_pids_max')
    assert args[pids_idx + 1] == '256'

    cpu_idx = args.index('--cgroup_cpu_ms_per_sec')
    assert args[cpu_idx + 1] == '2000'


def test_build_resource_limits_rlimit_fallback(backend):
    backend._cgroup_v2_available = False
    spec = BoxSpec(session_id='s', cmd='x', memory_mb=512, pids_limit=128)

    args = backend._build_resource_limits(spec)

    # Bug regression: --rlimit_as must NOT be used as the memory cap. It limits
    # virtual address space, which uv/node/Rust/JVM reserve in huge amounts, so
    # a small --rlimit_as aborts them instantly ("memory allocation failed",
    # exit 255) and silently broke every uvx stdio MCP server. There is no
    # RSS-based rlimit on modern Linux, so memory capping requires cgroups;
    # the fallback runs without a hard memory cap by design.
    assert "--rlimit_as" not in args

    nproc_idx = args.index('--rlimit_nproc')
    assert args[nproc_idx + 1] == '128'

    # Safe rlimits still apply.
    assert "--rlimit_fsize" in args
    assert "--rlimit_nofile" in args

    # cgroup flags should NOT be present.
    assert "--use_cgroupv2" not in args
    assert "--cgroup_mem_max" not in args


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


def test_detect_cgroup_v2_subtree_writable():
    """When writing to cgroup.subtree_control succeeds, report True.

    This is the authoritative probe: it mirrors exactly what nsjail does with
    --use_cgroupv2 (enable a controller on the root's subtree_control so the
    child cgroup can use it). A plain mkdir probe is insufficient because it
    succeeds even in a private cgroup namespace where the subtree_control write
    then fails with EBUSY.
    """

    def fake_exists(self):
        path = str(self)
        return path in (
            "/sys/fs/cgroup",
            "/sys/fs/cgroup/cgroup.controllers",
            "/sys/fs/cgroup/cgroup.subtree_control",
        )

    def fake_read_text(self, *a, **k):
        path = str(self)
        if path.endswith("cgroup.controllers"):
            return "cpuset cpu io memory hugetlb pids"
        if path.endswith("cgroup.subtree_control"):
            return ""  # nothing delegated yet -> probe will enable then disable
        raise FileNotFoundError(path)

    writes: list[str] = []

    def fake_write_text(self, data, *a, **k):
        writes.append(data)
        return len(data)

    with (
        mock.patch.object(pathlib.Path, "exists", fake_exists),
        mock.patch.object(pathlib.Path, "read_text", fake_read_text),
        mock.patch.object(pathlib.Path, "write_text", fake_write_text),
    ):
        assert NsjailBackend._detect_cgroup_v2() is True
    # Probe must enable then disable to leave host config untouched.
    assert writes == ["+memory", "-memory"]


def test_detect_cgroup_v2_private_cgroupns_ebusy_returns_false():
    """A private cgroup namespace (Docker/k8s default) lets mkdir succeed but
    rejects the subtree_control write with EBUSY (no-internal-process rule).
    The probe MUST catch this and report False so the backend uses the rlimit
    fallback instead of selecting a cgroup path that aborts nsjail (exit 255).
    """

    def fake_exists(self):
        path = str(self)
        return path in (
            "/sys/fs/cgroup",
            "/sys/fs/cgroup/cgroup.controllers",
            "/sys/fs/cgroup/cgroup.subtree_control",
        )

    def fake_read_text(self, *a, **k):
        path = str(self)
        if path.endswith("cgroup.controllers"):
            return "cpu memory pids"
        if path.endswith("cgroup.subtree_control"):
            return ""
        raise FileNotFoundError(path)

    def fake_write_text(self, data, *a, **k):
        raise OSError(16, "Device or resource busy")

    with (
        mock.patch.object(pathlib.Path, "exists", fake_exists),
        mock.patch.object(pathlib.Path, "read_text", fake_read_text),
        mock.patch.object(pathlib.Path, "write_text", fake_write_text),
    ):
        assert NsjailBackend._detect_cgroup_v2() is False


def test_detect_cgroup_v2_no_subtree_control_returns_false():
    """A read-only /sys/fs/cgroup with no subtree_control file reports False."""

    def fake_exists(self):
        path = str(self)
        return path in (
            "/sys/fs/cgroup",
            "/sys/fs/cgroup/cgroup.controllers",
        )

    with mock.patch.object(pathlib.Path, "exists", fake_exists):
        assert NsjailBackend._detect_cgroup_v2() is False


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
