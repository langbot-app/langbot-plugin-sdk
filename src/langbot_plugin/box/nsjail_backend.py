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
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
]

# Specific /etc entries required for dynamic linking and TLS.
_READONLY_ETC_ENTRIES: list[str] = [
    "/etc/alternatives",
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/ssl/certs",
    "/etc/localtime",
    "/etc/resolv.conf",  # needed when network=ON
]

# Essential character devices bind-mounted into the sandbox's /dev.
# /dev is a fresh empty tmpfs (see _build_args), so these nodes do not exist
# unless we bind them in from the host. Tooling that shells out for probes
# relies on them — notably `uv`/`uvx` redirects its glibc/musl detection
# subprocess to /dev/null; without it uv fails with "Could not detect either
# glibc version nor musl libc version" and the process exits before it can do
# anything (e.g. an stdio MCP server dies before the initialize handshake,
# surfacing as a misleading "Connection closed / please check URL").
_DEV_NODES: list[str] = [
    "/dev/null",
    "/dev/zero",
    "/dev/full",
    "/dev/random",
    "/dev/urandom",
    "/dev/tty",
]

_DEFAULT_BASE_DIR = "/tmp/langbot-box-nsjail"


class NsjailBackend(BaseSandboxBackend):
    """Lightweight sandbox backend using nsjail.

    Each ``exec`` invocation spawns an independent nsjail process.  Session
    state (workspace files) persists via a shared host directory that is
    bind-mounted into every invocation.
    """

    name = "nsjail"

    def __init__(
        self,
        logger: logging.Logger,
        nsjail_bin: str = "nsjail",
        base_dir: str = _DEFAULT_BASE_DIR,
    ):
        super().__init__(logger)
        self._nsjail_bin = nsjail_bin
        self._base_dir = pathlib.Path(base_dir)
        self._cgroup_v2_available: bool = False

    # ── lifecycle ─────────────────────────────────────────────────────

    async def is_available(self) -> bool:
        if shutil.which(self._nsjail_bin) is None:
            self.logger.info("nsjail binary not found in PATH")
            return False

        # Quick sanity check – nsjail --help exits 0.
        try:
            proc = await asyncio.create_subprocess_exec(
                self._nsjail_bin,
                "--help",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5)
            if proc.returncode != 0:
                self.logger.info("nsjail --help returned non-zero")
                return False
        except Exception as exc:
            self.logger.info(f"nsjail probe failed: {exc}")
            return False

        self._cgroup_v2_available = self._detect_cgroup_v2()
        if not self._cgroup_v2_available:
            self.logger.warning(
                "nsjail cgroup v2 limits unavailable (private cgroup namespace "
                "or read-only /sys/fs/cgroup); falling back to rlimit-based "
                "limits WITHOUT a hard memory cap. RLIMIT_AS is intentionally "
                "not used because it kills uv/node/etc. To enforce a memory "
                "cap, run the Box container in the host cgroup namespace "
                "(--cgroupns=host / compose `cgroup: host`) or set a "
                "container-level memory limit."
            )

        self._base_dir.mkdir(parents=True, exist_ok=True)
        return True

    async def start_session(self, spec: BoxSpec) -> BoxSessionInfo:
        validate_sandbox_security(spec)

        now = dt.datetime.now(dt.timezone.utc)
        session_dir_name = (
            f"{self.instance_id}_{spec.session_id}_{uuid.uuid4().hex[:8]}"
        )
        session_dir = self._base_dir / session_dir_name

        # Per-session writable directories.
        root_dir = session_dir / "root"
        workspace_dir = session_dir / "workspace"
        tmp_dir = session_dir / "tmp"
        home_dir = session_dir / "home"

        for d in (root_dir, workspace_dir, tmp_dir, home_dir):
            d.mkdir(parents=True, exist_ok=True)

        # When a host_path is mounted into the sandbox it becomes the nsjail
        # bind-mount source (see _build_mounts). nsjail requires the source to
        # already exist on the host, otherwise the bind-mount fails and the
        # command exits 255 with no stdout/stderr. The per-session loop above
        # never creates host_path (it lives outside session_dir), so ensure it
        # exists here. Read-only mounts intentionally are NOT auto-created: a
        # missing read-only source is a caller error that should surface.
        if (
            spec.host_path is not None
            and spec.host_path_mode == BoxHostMountMode.READ_WRITE
        ):
            os.makedirs(spec.host_path, exist_ok=True)

        # If host_path is specified, we will use it directly instead of the
        # per-session workspace when building nsjail args (see _build_mounts).
        meta = {
            "session_id": spec.session_id,
            "instance_id": self.instance_id,
            "host_path": spec.host_path,
            "host_path_mode": spec.host_path_mode.value if spec.host_path else None,
            "mount_path": spec.mount_path,
            "network": spec.network.value,
            "cpus": spec.cpus,
            "memory_mb": spec.memory_mb,
            "pids_limit": spec.pids_limit,
            "created_at": now.isoformat(),
        }
        (session_dir / "meta.json").write_text(json.dumps(meta, indent=2))

        self.logger.info(
            f"LangBot Box backend start_session: backend=nsjail "
            f"session_id={spec.session_id} session_dir={session_dir} "
            f"network={spec.network.value} "
            f"host_path={spec.host_path} host_path_mode={spec.host_path_mode.value} mount_path={spec.mount_path} "
            f"cpus={spec.cpus} memory_mb={spec.memory_mb} pids_limit={spec.pids_limit} "
            f"workspace_quota_mb={spec.workspace_quota_mb}"
        )

        return BoxSessionInfo(
            session_id=spec.session_id,
            backend_name=self.name,
            backend_session_id=str(session_dir),
            # Keep the requested logical image in metadata so runtime session
            # reuse sees later specs as compatible. nsjail still executes
            # against host-mounted system paths rather than a container image.
            image=spec.image,
            network=spec.network,
            host_path=spec.host_path,
            host_path_mode=spec.host_path_mode,
            mount_path=spec.mount_path,
            cpus=spec.cpus,
            memory_mb=spec.memory_mb,
            pids_limit=spec.pids_limit,
            read_only_rootfs=spec.read_only_rootfs,
            workspace_quota_mb=spec.workspace_quota_mb,
            persistent=spec.persistent,
            created_at=now,
            last_used_at=now,
        )

    async def exec(self, session: BoxSessionInfo, spec: BoxSpec) -> BoxExecutionResult:
        start = dt.datetime.now(dt.timezone.utc)
        session_dir = pathlib.Path(session.backend_session_id)

        args = self._build_nsjail_args(session, spec, session_dir)

        cmd_preview = spec.cmd.strip()
        if len(cmd_preview) > 400:
            cmd_preview = f"{cmd_preview[:397]}..."
        self.logger.info(
            f"LangBot Box backend exec: backend=nsjail "
            f"session_id={session.session_id} session_dir={session_dir} "
            f"workdir={spec.workdir} timeout_sec={spec.timeout_sec} "
            f"env_keys={sorted(spec.env.keys())} cmd={cmd_preview}"
        )

        result = await self._run_nsjail(args, timeout_sec=spec.timeout_sec)
        duration_ms = int(
            (dt.datetime.now(dt.timezone.utc) - start).total_seconds() * 1000
        )

        if result.timed_out:
            return BoxExecutionResult(
                session_id=session.session_id,
                backend_name=self.name,
                status=BoxExecutionStatus.TIMED_OUT,
                exit_code=None,
                stdout=result.stdout,
                stderr=result.stderr
                or f"Command timed out after {spec.timeout_sec} seconds.",
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
            f"LangBot Box backend stop_session: backend=nsjail "
            f"session_id={session.session_id} session_dir={session_dir}"
        )

        # Kill any lingering nsjail processes whose cwd is inside session_dir.
        await self._kill_session_processes(session_dir)

        try:
            if session_dir.exists():
                shutil.rmtree(session_dir)
        except Exception as exc:
            self.logger.warning(
                f"Failed to remove nsjail session dir {session_dir}: {exc}"
            )

    async def start_managed_process(
        self, session: BoxSessionInfo, spec
    ) -> asyncio.subprocess.Process:
        session_dir = pathlib.Path(session.backend_session_id)

        # Build a BoxSpec-like object so we can reuse _build_nsjail_args.
        # ManagedProcessSpec has command/args/cwd/env but not the full BoxSpec.
        inner_cmd = " ".join(
            [shlex.quote(spec.command), *[shlex.quote(a) for a in spec.args]]
        )
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
            read_only_rootfs=session.read_only_rootfs,
        )

        args = self._build_nsjail_args(session, pseudo_spec, session_dir)

        self.logger.info(
            f"LangBot Box backend start_managed_process: backend=nsjail "
            f"session_id={session.session_id} session_dir={session_dir} "
            f"cwd={spec.cwd} env_keys={sorted(spec.env.keys())} "
            f"command={spec.command} args={spec.args}"
        )

        return await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def cleanup_orphaned_containers(self, current_instance_id: str = ""):
        if not self._base_dir.exists():
            return

        for entry in self._base_dir.iterdir():
            if not entry.is_dir():
                continue

            # Session dirs are named: <instance_id>_<session_id>_<suffix>
            # If it doesn't start with the current instance_id, it's orphaned.
            if entry.name.startswith(f"{current_instance_id}_"):
                continue

            self.logger.info(f"Cleaning up orphaned nsjail session dir: {entry}")
            try:
                await self._kill_session_processes(entry)
                shutil.rmtree(entry)
            except Exception as exc:
                self.logger.warning(
                    f"Failed to clean up orphaned nsjail dir {entry}: {exc}"
                )

    # ── nsjail argument construction ──────────────────────────────────

    def _build_nsjail_args(
        self,
        session: BoxSessionInfo,
        spec: BoxSpec,
        session_dir: pathlib.Path,
    ) -> list[str]:
        args: list[str] = [self._nsjail_bin]

        # Mode: one-shot execution.
        args.extend(["--mode", "o"])

        # nsjail enables the relevant clone namespaces by default. Some
        # versions do not expose positive --clone_new* flags, only disable
        # flags, so rely on defaults for broad compatibility.

        # Use a per-session chroot root so nsjail can create mount targets
        # without needing write access to the host root.
        root_dir = session_dir / "root"
        root_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_chroot_mount_targets(root_dir, session, spec)
        args.extend(["--chroot", str(root_dir)])

        # Network namespace.
        if spec.network != BoxNetworkMode.OFF:
            args.append("--disable_clone_newnet")

        # Read-only system mounts.
        args.extend(self._build_readonly_mounts(spec.network))

        # Writable per-session mounts.
        args.extend(self._build_writable_mounts(session, spec, session_dir))

        # Isolated /proc and minimal /dev.
        args.extend(["--mount", "none:/proc:proc:rw"])
        args.extend(["--mount", "none:/dev:tmpfs:rw"])

        # /dev is a fresh empty tmpfs, so bind in the essential character
        # devices. Without /dev/null in particular, uv's glibc/musl detection
        # subprocess fails and any uvx-launched process (e.g. stdio MCP servers)
        # exits before doing useful work. Mounted read-write so writes to
        # /dev/null behave normally.
        for dev in _DEV_NODES:
            if os.path.exists(dev):
                args.extend(["--bindmount", f"{dev}:{dev}"])

        # Working directory.
        args.extend(["--cwd", spec.workdir])

        # Environment variables.
        args.extend(["--env", "PYTHONUNBUFFERED=1"])
        args.extend(["--env", "HOME=/home"])
        args.extend(
            [
                "--env",
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            ]
        )
        for key, value in spec.env.items():
            args.extend(["--env", f"{key}={value}"])

        # Resource limits.
        args.extend(self._build_resource_limits(spec))

        # Suppress nsjail's own log output.
        args.append("--really_quiet")

        # The actual command.
        quoted_workdir = shlex.quote(spec.workdir)
        user_cmd = f"mkdir -p {quoted_workdir} && cd {quoted_workdir} && {spec.cmd}"
        args.extend(["--", "/bin/sh", "-lc", user_cmd])

        return args

    def _build_readonly_mounts(self, network: BoxNetworkMode) -> list[str]:
        args: list[str] = []

        for path in _READONLY_SYSTEM_MOUNTS:
            if os.path.exists(path):
                args.extend(["--bindmount_ro", f"{path}:{path}"])

        for path in _READONLY_ETC_ENTRIES:
            # /etc/resolv.conf is only needed when network is ON.
            if path == "/etc/resolv.conf" and network == BoxNetworkMode.OFF:
                continue
            if os.path.exists(path):
                args.extend(["--bindmount_ro", f"{path}:{path}"])

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
                args.extend(["--bindmount_ro", f"{spec.host_path}:{spec.mount_path}"])
            else:
                args.extend(["--bindmount", f"{spec.host_path}:{spec.mount_path}"])
        else:
            workspace_dir = session_dir / "workspace"
            args.extend(["--bindmount", f"{workspace_dir}:{spec.mount_path}"])

        for mount in spec.extra_mounts:
            if mount.mode == BoxHostMountMode.READ_ONLY:
                args.extend(["--bindmount_ro", f"{mount.host_path}:{mount.mount_path}"])
            elif mount.mode == BoxHostMountMode.READ_WRITE:
                args.extend(["--bindmount", f"{mount.host_path}:{mount.mount_path}"])

        # /tmp and /home are always per-session writable.
        tmp_dir = session_dir / "tmp"
        home_dir = session_dir / "home"
        args.extend(["--bindmount", f"{tmp_dir}:/tmp"])
        args.extend(["--bindmount", f"{home_dir}:/home"])

        return args

    def _ensure_chroot_mount_targets(
        self,
        root_dir: pathlib.Path,
        session: BoxSessionInfo,
        spec: BoxSpec,
    ) -> None:
        mount_paths = {
            "/proc",
            "/dev",
            "/tmp",
            "/home",
            spec.mount_path,
            session.mount_path,
        }
        mount_paths.update(_READONLY_SYSTEM_MOUNTS)
        mount_paths.update(_READONLY_ETC_ENTRIES)
        for mount in spec.extra_mounts:
            mount_paths.add(mount.mount_path)

        for mount_path in mount_paths:
            if not mount_path:
                continue
            target = root_dir / mount_path.lstrip("/")
            try:
                if os.path.isfile(mount_path):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch(exist_ok=True)
                else:
                    target.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                self.logger.debug(
                    f"Failed to prepare nsjail mount target {target}: {exc}"
                )

    def _build_resource_limits(self, spec: BoxSpec) -> list[str]:
        args: list[str] = []

        if self._cgroup_v2_available:
            # cgroup v2 – precise limits. nsjail defaults to the legacy cgroup
            # v1 layout, so we MUST opt into v2 explicitly; without this flag
            # nsjail tries to mkdir under /sys/fs/cgroup/<controller>/... (v1
            # paths) and aborts on a v2-only host. The writability of the v2
            # root is already verified in _detect_cgroup_v2().
            args.append("--use_cgroupv2")
            memory_bytes = spec.memory_mb * 1024 * 1024
            args.extend(["--cgroup_mem_max", str(memory_bytes)])
            args.extend(["--cgroup_pids_max", str(spec.pids_limit)])
            cpu_ms = int(spec.cpus * 1000)
            args.extend(["--cgroup_cpu_ms_per_sec", str(cpu_ms)])
        else:
            # rlimit fallback – used whenever cgroup v2 delegation is not usable
            # (private cgroup namespace -> EBUSY, or read-only /sys/fs/cgroup).
            #
            # We deliberately do NOT set --rlimit_as for the memory cap.
            # RLIMIT_AS limits *virtual* address space, not resident memory, and
            # modern runtimes reserve huge virtual mappings up front: uv/Rust
            # (and Go/JVM/Node) mmap gigabytes of address space even to do tiny
            # work, so a 512 MB --rlimit_as aborts them instantly with
            # "memory allocation of N bytes failed" (exit 255) — which is what
            # silently broke every uvx-based stdio MCP server in containerized
            # nsjail deployments. There is no RSS-based rlimit on modern Linux
            # (RLIMIT_RSS is ignored), so accurate memory capping REQUIRES
            # cgroups. Operators who need a hard memory cap must run the Box
            # container in the host cgroup namespace (--cgroupns=host /
            # compose `cgroup: host`); otherwise bound memory at the container
            # level (e.g. compose `mem_limit`). We still apply the pid cap,
            # which is a real rlimit that does not break runtimes.
            args.extend(["--rlimit_nproc", str(spec.pids_limit)])

        # Always set these rlimits regardless of cgroup mode. These are safe
        # for modern runtimes (unlike RLIMIT_AS).
        args.extend(["--rlimit_fsize", "512"])  # max file size 512 MB
        args.extend(["--rlimit_nofile", "256"])  # max open fds

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
        """Check whether nsjail's ``--use_cgroupv2`` path will actually work.

        nsjail (with ``--use_cgroupv2``) moves itself into a fresh child cgroup
        it ``mkdir``s under the cgroup v2 mount root, then enables controllers
        for that child by writing ``+memory`` (etc.) to the ROOT's
        ``cgroup.subtree_control``. BOTH operations must succeed.

        Probing ``mkdir`` alone is NOT sufficient and produces a false positive
        in the common containerized case: inside a **private** cgroup namespace
        (Docker/k8s default) the container's own cgroup root already contains
        live processes (the Box runtime itself), so the kernel's
        "no-internal-process" rule rejects the ``cgroup.subtree_control`` write
        with ``EBUSY`` even though ``mkdir`` under the root succeeds. nsjail then
        aborts and every sandbox launch exits 255. Conversely a read-only
        ``/sys/fs/cgroup`` (another common case) fails the ``mkdir``.

        So we probe the AUTHORITATIVE operation: a real write to
        ``cgroup.subtree_control``. We only consider it available when that
        write succeeds, which is exactly nsjail's requirement. Containerized
        deployments that need cgroup limits must run the Box container in the
        host cgroup namespace (``--cgroupns=host`` / compose ``cgroup: host``);
        otherwise this returns False and the backend uses the rlimit fallback.
        """
        cgroup_mount = pathlib.Path("/sys/fs/cgroup")
        if not cgroup_mount.exists():
            return False
        # cgroup v2 has a single hierarchy with a cgroup.controllers file.
        controllers = cgroup_mount / "cgroup.controllers"
        subtree_control = cgroup_mount / "cgroup.subtree_control"
        if not controllers.exists() or not subtree_control.exists():
            return False
        # nsjail enables the controllers it needs (memory, pids, cpu) on the
        # child cgroup, which requires them to be delegated via the root's
        # subtree_control. Only probe controllers actually present here.
        try:
            available = set(controllers.read_text().split())
        except Exception:
            return False
        wanted = [c for c in ("memory", "pids", "cpu") if c in available]
        if not wanted:
            return False
        # Authoritative writability probe: re-arm a controller that is already
        # enabled (idempotent no-op), or briefly toggle one that is not. A
        # successful write proves nsjail's subtree_control write will also
        # succeed; EBUSY (private cgroupns) or EACCES/EROFS (read-only mount)
        # all surface here and correctly select the rlimit fallback.
        try:
            enabled = set(subtree_control.read_text().split())
        except Exception:
            return False
        probe_controller = wanted[0]
        try:
            if probe_controller in enabled:
                # Already delegated: re-writing the same enable is a harmless
                # no-op that still exercises the write permission + EBUSY rule.
                subtree_control.write_text(f"+{probe_controller}")
            else:
                # Not yet delegated: enable then immediately disable to leave
                # the host configuration untouched.
                subtree_control.write_text(f"+{probe_controller}")
                try:
                    subtree_control.write_text(f"-{probe_controller}")
                except Exception:
                    pass
        except Exception:
            return False
        return True

    async def _kill_session_processes(self, session_dir: pathlib.Path) -> None:
        """Best-effort kill of nsjail processes associated with a session dir.

        We scan /proc for nsjail processes whose command line contains the
        session directory path.
        """
        session_path_str = str(session_dir)
        proc_dir = pathlib.Path("/proc")
        if not proc_dir.exists():
            return

        for pid_dir in proc_dir.iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                cmdline = (
                    (pid_dir / "cmdline").read_bytes().decode("utf-8", errors="replace")
                )
                if self._nsjail_bin in cmdline and session_path_str in cmdline:
                    pid = int(pid_dir.name)
                    os.kill(pid, signal.SIGKILL)
                    self.logger.info(f"Killed orphaned nsjail process {pid}")
            except (OSError, ValueError):
                continue

    @staticmethod
    def _clip_captured_bytes(
        data: bytes, total_size: int, limit: int = _MAX_RAW_OUTPUT_BYTES
    ) -> str:
        text = data.decode("utf-8", errors="replace").strip()
        if total_size > limit:
            text += f"\n... [raw output clipped at {limit} bytes, {total_size - limit} bytes discarded]"
        return text

    @staticmethod
    async def _read_stream(
        stream: asyncio.StreamReader | None,
        limit: int = _MAX_RAW_OUTPUT_BYTES,
    ) -> tuple[bytes, int]:
        if stream is None:
            return b"", 0

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
