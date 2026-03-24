from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import pathlib
import shlex
import shutil
import signal
import uuid

from .backend import BaseSandboxBackend, _CommandResult, _MAX_RAW_OUTPUT_BYTES
from .errors import BoxError
from .models import (
    BoxExecutionResult,
    BoxExecutionStatus,
    BoxHostMountMode,
    BoxNetworkMode,
    BoxSessionInfo,
    BoxSpec,
)
from .security import validate_sandbox_security

# System directories to mount read-only inside the sandbox.
# Only well-known paths needed for running Python/Node/shell commands.
_READONLY_SYSTEM_MOUNTS: list[str] = [
    '/usr',
    '/lib',
    '/lib64',
    '/bin',
    '/sbin',
]

# Specific /etc entries required for dynamic linking and TLS.
_READONLY_ETC_ENTRIES: list[str] = [
    '/etc/alternatives',
    '/etc/ld.so.cache',
    '/etc/ld.so.conf',
    '/etc/ld.so.conf.d',
    '/etc/ssl/certs',
    '/etc/localtime',
    '/etc/resolv.conf',  # needed when network=ON
]

_DEFAULT_BASE_DIR = '/tmp/langbot-box-nsjail'


class NsjailBackend(BaseSandboxBackend):
    """Lightweight sandbox backend using nsjail.

    Each ``exec`` invocation spawns an independent nsjail process.  Session
    state (workspace files) persists via a shared host directory that is
    bind-mounted into every invocation.
    """

    name = 'nsjail'

    def __init__(
        self,
        logger: logging.Logger,
        nsjail_bin: str = 'nsjail',
        base_dir: str = _DEFAULT_BASE_DIR,
    ):
        super().__init__(logger)
        self._nsjail_bin = nsjail_bin
        self._base_dir = pathlib.Path(base_dir)
        self._cgroup_v2_available: bool = False

    # ── lifecycle ─────────────────────────────────────────────────────

    async def is_available(self) -> bool:
        if shutil.which(self._nsjail_bin) is None:
            self.logger.info('nsjail binary not found in PATH')
            return False

        # Quick sanity check – nsjail --help exits 0.
        try:
            proc = await asyncio.create_subprocess_exec(
                self._nsjail_bin, '--help',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5)
            if proc.returncode != 0:
                self.logger.info('nsjail --help returned non-zero')
                return False
        except Exception as exc:
            self.logger.info(f'nsjail probe failed: {exc}')
            return False

        self._cgroup_v2_available = self._detect_cgroup_v2()
        if not self._cgroup_v2_available:
            self.logger.warning(
                'cgroup v2 not available for nsjail; '
                'falling back to rlimit-based resource limits'
            )

        self._base_dir.mkdir(parents=True, exist_ok=True)
        return True

    async def start_session(self, spec: BoxSpec) -> BoxSessionInfo:
        validate_sandbox_security(spec)

        now = dt.datetime.now(dt.timezone.utc)
        session_dir_name = f'{self.instance_id}_{spec.session_id}_{uuid.uuid4().hex[:8]}'
        session_dir = self._base_dir / session_dir_name

        # Per-session writable directories.
        workspace_dir = session_dir / 'workspace'
        tmp_dir = session_dir / 'tmp'
        home_dir = session_dir / 'home'

        for d in (workspace_dir, tmp_dir, home_dir):
            d.mkdir(parents=True, exist_ok=True)

        # If host_path is specified, we will use it directly instead of the
        # per-session workspace when building nsjail args (see _build_mounts).
        meta = {
            'session_id': spec.session_id,
            'instance_id': self.instance_id,
            'host_path': spec.host_path,
            'host_path_mode': spec.host_path_mode.value if spec.host_path else None,
            'mount_path': spec.mount_path,
            'network': spec.network.value,
            'cpus': spec.cpus,
            'memory_mb': spec.memory_mb,
            'pids_limit': spec.pids_limit,
            'created_at': now.isoformat(),
        }
        (session_dir / 'meta.json').write_text(json.dumps(meta, indent=2))

        self.logger.info(
            f'LangBot Box backend start_session: backend=nsjail '
            f'session_id={spec.session_id} session_dir={session_dir} '
            f'network={spec.network.value} '
            f'host_path={spec.host_path} host_path_mode={spec.host_path_mode.value} mount_path={spec.mount_path} '
            f'cpus={spec.cpus} memory_mb={spec.memory_mb} pids_limit={spec.pids_limit}'
        )

        return BoxSessionInfo(
            session_id=spec.session_id,
            backend_name=self.name,
            backend_session_id=str(session_dir),
            image='host',
            network=spec.network,
            host_path=spec.host_path,
            host_path_mode=spec.host_path_mode,
            mount_path=spec.mount_path,
            cpus=spec.cpus,
            memory_mb=spec.memory_mb,
            pids_limit=spec.pids_limit,
            read_only_rootfs=True,  # always true for nsjail
            created_at=now,
            last_used_at=now,
        )

    async def exec(self, session: BoxSessionInfo, spec: BoxSpec) -> BoxExecutionResult:
        start = dt.datetime.now(dt.timezone.utc)
        session_dir = pathlib.Path(session.backend_session_id)

        args = self._build_nsjail_args(session, spec, session_dir)

        cmd_preview = spec.cmd.strip()
        if len(cmd_preview) > 400:
            cmd_preview = f'{cmd_preview[:397]}...'
        self.logger.info(
            f'LangBot Box backend exec: backend=nsjail '
            f'session_id={session.session_id} session_dir={session_dir} '
            f'workdir={spec.workdir} timeout_sec={spec.timeout_sec} '
            f'env_keys={sorted(spec.env.keys())} cmd={cmd_preview}'
        )

        result = await self._run_nsjail(args, timeout_sec=spec.timeout_sec)
        duration_ms = int((dt.datetime.now(dt.timezone.utc) - start).total_seconds() * 1000)

        if result.timed_out:
            return BoxExecutionResult(
                session_id=session.session_id,
                backend_name=self.name,
                status=BoxExecutionStatus.TIMED_OUT,
                exit_code=None,
                stdout=result.stdout,
                stderr=result.stderr or f'Command timed out after {spec.timeout_sec} seconds.',
                duration_ms=duration_ms,
            )

        return BoxExecutionResult(
            session_id=session.session_id,
            backend_name=self.name,
            status=BoxExecutionStatus.COMPLETED,
            exit_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
        )

    async def stop_session(self, session: BoxSessionInfo):
        session_dir = pathlib.Path(session.backend_session_id)
        self.logger.info(
            f'LangBot Box backend stop_session: backend=nsjail '
            f'session_id={session.session_id} session_dir={session_dir}'
        )

        # Kill any lingering nsjail processes whose cwd is inside session_dir.
        await self._kill_session_processes(session_dir)

        try:
            if session_dir.exists():
                shutil.rmtree(session_dir)
        except Exception as exc:
            self.logger.warning(f'Failed to remove nsjail session dir {session_dir}: {exc}')

    async def start_managed_process(
        self, session: BoxSessionInfo, spec
    ) -> asyncio.subprocess.Process:
        session_dir = pathlib.Path(session.backend_session_id)

        # Build a BoxSpec-like object so we can reuse _build_nsjail_args.
        # ManagedProcessSpec has command/args/cwd/env but not the full BoxSpec.
        inner_cmd = ' '.join([shlex.quote(spec.command), *[shlex.quote(a) for a in spec.args]])
        pseudo_spec = BoxSpec(
            cmd=inner_cmd,
            workdir=spec.cwd,
            timeout_sec=86400,  # not used here
            network=session.network,
            session_id=session.session_id,
            env=spec.env,
            host_path=session.host_path,
            host_path_mode=session.host_path_mode,
            mount_path=session.mount_path,
            cpus=session.cpus,
            memory_mb=session.memory_mb,
            pids_limit=session.pids_limit,
            read_only_rootfs=True,
        )

        args = self._build_nsjail_args(session, pseudo_spec, session_dir)

        self.logger.info(
            f'LangBot Box backend start_managed_process: backend=nsjail '
            f'session_id={session.session_id} session_dir={session_dir} '
            f'cwd={spec.cwd} env_keys={sorted(spec.env.keys())} '
            f'command={spec.command} args={spec.args}'
        )

        return await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def cleanup_orphaned_containers(self, current_instance_id: str = ''):
        if not self._base_dir.exists():
            return

        for entry in self._base_dir.iterdir():
            if not entry.is_dir():
                continue

            # Session dirs are named: <instance_id>_<session_id>_<suffix>
            # If it doesn't start with the current instance_id, it's orphaned.
            if entry.name.startswith(f'{current_instance_id}_'):
                continue

            self.logger.info(f'Cleaning up orphaned nsjail session dir: {entry}')
            try:
                await self._kill_session_processes(entry)
                shutil.rmtree(entry)
            except Exception as exc:
                self.logger.warning(f'Failed to clean up orphaned nsjail dir {entry}: {exc}')

    # ── nsjail argument construction ──────────────────────────────────

    def _build_nsjail_args(
        self,
        session: BoxSessionInfo,
        spec: BoxSpec,
        session_dir: pathlib.Path,
    ) -> list[str]:
        args: list[str] = [self._nsjail_bin]

        # Mode: one-shot execution.
        args.extend(['--mode', 'o'])

        # Namespace isolation.
        args.extend([
            '--clone_newuser',
            '--clone_newns',
            '--clone_newpid',
            '--clone_newipc',
            '--clone_newuts',
            '--clone_newcgroup',
        ])

        # Network namespace.
        if spec.network == BoxNetworkMode.OFF:
            args.append('--clone_newnet')
        else:
            args.append('--disable_clone_newnet')

        # Read-only system mounts.
        args.extend(self._build_readonly_mounts(spec.network))

        # Writable per-session mounts.
        args.extend(self._build_writable_mounts(session, spec, session_dir))

        # Isolated /proc and minimal /dev.
        args.extend(['--mount', 'none:/proc:proc:rw'])
        args.extend(['--mount', 'none:/dev:tmpfs:rw'])

        # Working directory.
        args.extend(['--cwd', spec.workdir])

        # Environment variables.
        args.extend(['--env', 'PYTHONUNBUFFERED=1'])
        args.extend(['--env', 'HOME=/home'])
        args.extend(['--env', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'])
        for key, value in spec.env.items():
            args.extend(['--env', f'{key}={value}'])

        # Resource limits.
        args.extend(self._build_resource_limits(spec))

        # Suppress nsjail's own log output.
        args.append('--really_quiet')

        # The actual command.
        quoted_workdir = shlex.quote(spec.workdir)
        user_cmd = f'mkdir -p {quoted_workdir} && cd {quoted_workdir} && {spec.cmd}'
        args.extend(['--', 'sh', '-lc', user_cmd])

        return args

    def _build_readonly_mounts(self, network: BoxNetworkMode) -> list[str]:
        args: list[str] = []

        for path in _READONLY_SYSTEM_MOUNTS:
            if os.path.exists(path):
                args.extend(['--bindmount_ro', f'{path}:{path}'])

        for path in _READONLY_ETC_ENTRIES:
            # /etc/resolv.conf is only needed when network is ON.
            if path == '/etc/resolv.conf' and network == BoxNetworkMode.OFF:
                continue
            if os.path.exists(path):
                args.extend(['--bindmount_ro', f'{path}:{path}'])

        return args

    def _build_writable_mounts(
        self,
        session: BoxSessionInfo,
        spec: BoxSpec,
        session_dir: pathlib.Path,
    ) -> list[str]:
        args: list[str] = []

        # Workspace mount.
        if spec.host_path is not None and spec.host_path_mode != BoxHostMountMode.NONE:
            if spec.host_path_mode == BoxHostMountMode.READ_ONLY:
                args.extend(['--bindmount_ro', f'{spec.host_path}:{spec.mount_path}'])
            else:
                args.extend(['--rw_bind', f'{spec.host_path}:{spec.mount_path}'])
        else:
            workspace_dir = session_dir / 'workspace'
            args.extend(['--rw_bind', f'{workspace_dir}:{spec.mount_path}'])

        # /tmp and /home are always per-session writable.
        tmp_dir = session_dir / 'tmp'
        home_dir = session_dir / 'home'
        args.extend(['--rw_bind', f'{tmp_dir}:/tmp'])
        args.extend(['--rw_bind', f'{home_dir}:/home'])

        return args

    def _build_resource_limits(self, spec: BoxSpec) -> list[str]:
        args: list[str] = []

        if self._cgroup_v2_available:
            # cgroup v2 – precise limits.
            memory_bytes = spec.memory_mb * 1024 * 1024
            args.extend(['--cgroup_mem_max', str(memory_bytes)])
            args.extend(['--cgroup_pids_max', str(spec.pids_limit)])
            cpu_ms = int(spec.cpus * 1000)
            args.extend(['--cgroup_cpu_ms_per_sec', str(cpu_ms)])
        else:
            # rlimit fallback – best-effort.
            args.extend(['--rlimit_as', str(spec.memory_mb)])
            args.extend(['--rlimit_nproc', str(spec.pids_limit)])

        # Always set these rlimits regardless of cgroup mode.
        args.extend(['--rlimit_fsize', '512'])    # max file size 512 MB
        args.extend(['--rlimit_nofile', '256'])    # max open fds

        return args

    # ── process execution ─────────────────────────────────────────────

    async def _run_nsjail(
        self,
        args: list[str],
        timeout_sec: int,
    ) -> _CommandResult:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_task = asyncio.create_task(self._read_stream(process.stdout))
        stderr_task = asyncio.create_task(self._read_stream(process.stderr))

        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            process.kill()
            timed_out = True
            await process.wait()

        stdout_bytes, stdout_total = await stdout_task
        stderr_bytes, stderr_total = await stderr_task

        return _CommandResult(
            return_code=process.returncode if not timed_out else -1,
            stdout=self._clip_captured_bytes(stdout_bytes, stdout_total),
            stderr=self._clip_captured_bytes(stderr_bytes, stderr_total),
            timed_out=timed_out,
        )

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _detect_cgroup_v2() -> bool:
        """Check whether the host runs cgroup v2 and we can write to it."""
        cgroup_mount = pathlib.Path('/sys/fs/cgroup')
        if not cgroup_mount.exists():
            return False
        # cgroup v2 has a single hierarchy with cgroup.controllers file.
        controllers = cgroup_mount / 'cgroup.controllers'
        if not controllers.exists():
            return False
        # Check if we can write to a cgroup subtree (needed for nsjail).
        # A rough heuristic: if the user owns a cgroup directory we're probably
        # running under systemd user delegation.
        user_slice = cgroup_mount / f'user.slice/user-{os.getuid()}.slice'
        if user_slice.exists():
            return True
        # If running as root (uid 0), cgroup v2 is always usable.
        if os.getuid() == 0:
            return True
        # Conservative: if we can't confirm writability, report unavailable.
        return False

    async def _kill_session_processes(self, session_dir: pathlib.Path) -> None:
        """Best-effort kill of nsjail processes associated with a session dir.

        We scan /proc for nsjail processes whose command line contains the
        session directory path.
        """
        session_path_str = str(session_dir)
        proc_dir = pathlib.Path('/proc')
        if not proc_dir.exists():
            return

        for pid_dir in proc_dir.iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                cmdline = (pid_dir / 'cmdline').read_bytes().decode('utf-8', errors='replace')
                if self._nsjail_bin in cmdline and session_path_str in cmdline:
                    pid = int(pid_dir.name)
                    os.kill(pid, signal.SIGKILL)
                    self.logger.info(f'Killed orphaned nsjail process {pid}')
            except (OSError, ValueError):
                continue

    @staticmethod
    def _clip_captured_bytes(
        data: bytes, total_size: int, limit: int = _MAX_RAW_OUTPUT_BYTES
    ) -> str:
        text = data.decode('utf-8', errors='replace').strip()
        if total_size > limit:
            text += f'\n... [raw output clipped at {limit} bytes, {total_size - limit} bytes discarded]'
        return text

    @staticmethod
    async def _read_stream(
        stream: asyncio.StreamReader | None,
        limit: int = _MAX_RAW_OUTPUT_BYTES,
    ) -> tuple[bytes, int]:
        if stream is None:
            return b'', 0

        chunks = bytearray()
        total_size = 0
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            total_size += len(chunk)
            remaining = limit - len(chunks)
            if remaining > 0:
                chunks.extend(chunk[:remaining])

        return bytes(chunks), total_size
