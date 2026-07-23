from __future__ import annotations

import asyncio
import collections
import contextlib
import dataclasses
import datetime as dt
import json
import logging
import os
from pathlib import Path
import uuid
import weakref
from typing import TYPE_CHECKING

from .backend import BaseSandboxBackend, DockerBackend
from .nsjail_backend import NsjailBackend
from .errors import (
    BoxBackendUnavailableError,
    BoxCapacityExceededError,
    BoxManagedProcessNotFoundError,
    BoxSessionConflictError,
    BoxSessionNotFoundError,
    BoxRuntimeUnavailableError,
    BoxValidationError,
)
from .models import (
    BoxExecutionResult,
    BoxExecutionStatus,
    BoxManagedProcessInfo,
    BoxManagedProcessSpec,
    BoxManagedProcessStatus,
    BoxSessionInfo,
    BoxSpec,
)
from .skill_store import BoxSkillStore

if TYPE_CHECKING:
    from .e2b_backend import E2BSandboxBackend

_UTC = dt.timezone.utc
_MANAGED_PROCESS_STDERR_PREVIEW_LIMIT = 4000
_REAPER_INTERVAL_SEC = 30


def _resolve_local_path(path_value: str, *, base: str | None = None) -> str:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (Path(base).expanduser() / path) if base else (Path.cwd() / path)
    return str(path.resolve())


@dataclasses.dataclass(slots=True)
class _ManagedProcess:
    spec: BoxManagedProcessSpec
    process: asyncio.subprocess.Process
    started_at: dt.datetime
    attach_lock: asyncio.Lock
    stderr_chunks: collections.deque[str]
    stderr_total_len: int = 0
    exit_code: int | None = None
    exited_at: dt.datetime | None = None

    @property
    def is_running(self) -> bool:
        return self.exit_code is None and self.process.returncode is None


@dataclasses.dataclass(slots=True)
class _RuntimeSession:
    info: BoxSessionInfo
    lock: asyncio.Lock
    managed_processes: dict[str, _ManagedProcess] = dataclasses.field(
        default_factory=dict
    )
    # Signature of the extra bind mounts the container was created with. Used
    # to detect when a reused session would be missing newly-requested mounts.
    extra_mounts_key: frozenset[tuple[str, str, str]] = frozenset()
    closing: bool = False


def _compute_extra_mounts_key(spec: BoxSpec) -> frozenset[tuple[str, str, str]]:
    """Signature of a spec's effective extra bind mounts.

    Mirrors the backend's mount filtering (``mode == "none"`` mounts are not
    bind-mounted; see ``DockerBackend.start_session``) so two specs that produce
    the same set of ``-v`` flags compare equal. A bind mount cannot be added to
    an already-running container, so this is used to detect when a reused
    session's container would be missing newly-requested mounts and must be
    recreated.
    """
    key: set[tuple[str, str, str]] = set()
    for mount in spec.extra_mounts:
        mode_val = mount.mode.value if hasattr(mount.mode, "value") else str(mount.mode)
        if mode_val == "none":
            continue
        key.add((mount.host_path, mount.mount_path, mode_val))
    return frozenset(key)


class BoxRuntime:
    def __init__(
        self,
        logger: logging.Logger,
        backends: list[BaseSandboxBackend] | None = None,
        session_ttl_sec: int = 300,
        max_sessions: int = 64,
        max_managed_processes: int = 64,
        max_completed_processes: int = 256,
        completed_process_retention_sec: int = 300,
    ):
        self.logger = logger

        # Load configuration from environment variable (passed by LangBot)
        self._box_config: dict = {}
        config_json = os.getenv("LANGBOT_BOX_CONFIG", "")
        if config_json:
            try:
                self._box_config = json.loads(config_json)
            except json.JSONDecodeError:
                logger.warning(
                    f"Failed to parse LANGBOT_BOX_CONFIG: {config_json[:100]}"
                )

        # Build backend list
        if backends is None:
            backends = [
                DockerBackend(logger),
                NsjailBackend(logger),
                self._create_e2b_backend(logger),
            ]

        self.backends = backends
        self.session_ttl_sec = session_ttl_sec
        limits = self._box_config.get("limits") or {}
        self.max_sessions = int(limits.get("max_sessions", max_sessions))
        self.max_managed_processes = int(
            limits.get("max_managed_processes", max_managed_processes)
        )
        self.max_completed_processes = int(
            limits.get("max_completed_processes", max_completed_processes)
        )
        self.completed_process_retention_sec = int(
            limits.get(
                "completed_process_retention_sec", completed_process_retention_sec
            )
        )
        self._backend: BaseSandboxBackend | None = None
        self._backend_lock = asyncio.Lock()
        self._sessions: dict[str, _RuntimeSession] = {}
        self._lock = asyncio.Lock()
        self._session_operation_locks: weakref.WeakValueDictionary[
            str, asyncio.Lock
        ] = weakref.WeakValueDictionary()
        self._session_leases: collections.Counter[str] = collections.Counter()
        self._creating_session_tasks: dict[str, asyncio.Task] = {}
        self._managed_starting_count = 0
        self._shutdown_in_progress = False
        self._reaper_task: asyncio.Task | None = None
        self._active_exec_counts: collections.Counter[str] = collections.Counter()
        self._closing_session_tasks: dict[str, asyncio.Task[None]] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self.instance_id = uuid.uuid4().hex[:12]
        self.skill_store = BoxSkillStore(self._box_config)

    def _create_e2b_backend(self, logger: logging.Logger) -> "E2BSandboxBackend | None":
        """Create E2B backend if package is installed."""
        try:
            from .e2b_backend import E2BSandboxBackend

            return E2BSandboxBackend(logger)
        except ImportError:
            logger.debug("e2b package not installed, E2B backend unavailable")
            return None

    async def initialize(self):
        # Apply configuration from env var to all backends
        if self._box_config:
            self._apply_config_to_backends(self._box_config)
            self._ensure_default_workspace()

        self._backend = await self._select_backend()
        if self._backend is not None:
            self._backend.instance_id = self.instance_id
            try:
                await self._backend.cleanup_orphaned_containers(self.instance_id)
            except Exception as exc:
                self.logger.warning(
                    f"LangBot Box orphan container cleanup failed: {exc}"
                )

        self.start_background_reaper()

    def init(self, config: dict) -> None:
        """Initialize with full box configuration from LangBot.

        Called via RPC (INIT action) when connecting over WebSocket.
        """
        self._box_config.update(config)
        limits = self._box_config.get("limits") or {}
        self.max_sessions = int(limits.get("max_sessions", self.max_sessions))
        self.max_managed_processes = int(
            limits.get("max_managed_processes", self.max_managed_processes)
        )
        self.max_completed_processes = int(
            limits.get("max_completed_processes", self.max_completed_processes)
        )
        self.completed_process_retention_sec = int(
            limits.get(
                "completed_process_retention_sec",
                self.completed_process_retention_sec,
            )
        )
        self._apply_config_to_backends(config)
        self.skill_store.update_config(self._box_config)
        self._ensure_default_workspace()
        if not self._sessions:
            self._backend = None

    def _local_config(self) -> dict:
        return self._box_config.get("local") or {}

    def _host_root(self) -> str | None:
        host_root = str(self._local_config().get("host_root", "") or "").strip()
        if not host_root:
            return None
        return _resolve_local_path(host_root)

    def _default_workspace(self) -> str | None:
        host_root = self._host_root()
        default_workspace = str(
            self._local_config().get("default_workspace", "") or ""
        ).strip()
        if not default_workspace:
            if host_root is None:
                return None
            default_workspace = "default"
        return _resolve_local_path(default_workspace, base=host_root)

    def _allowed_mount_roots(self) -> list[str]:
        configured_roots = self._local_config().get("allowed_mount_roots", [])
        if isinstance(configured_roots, str):
            configured_roots = [
                item.strip() for item in configured_roots.split(",") if item.strip()
            ]

        host_root = self._host_root()
        roots: list[str] = []
        for root in configured_roots or []:
            root_value = str(root or "").strip()
            if root_value:
                # Mount allow-list entries are host paths. Relative values in
                # the shipped config (for example ``./data/box``) are relative
                # to the runtime working directory, not nested under host_root.
                roots.append(_resolve_local_path(root_value))

        if not roots and host_root is not None:
            roots.append(host_root)
        return roots

    def _ensure_default_workspace(self) -> None:
        default_workspace = self._default_workspace()
        if default_workspace is None:
            return

        if os.path.isdir(default_workspace):
            return

        if os.path.exists(default_workspace):
            raise BoxValidationError(
                "box.local.default_workspace must point to a directory on the Box runtime host"
            )

        allowed_roots = self._allowed_mount_roots()
        if not allowed_roots:
            raise BoxValidationError(
                "box.local.default_workspace cannot be created because no allowed_mount_roots are configured"
            )

        for allowed_root in allowed_roots:
            if default_workspace == allowed_root or default_workspace.startswith(
                f"{allowed_root}{os.sep}"
            ):
                os.makedirs(default_workspace, exist_ok=True)
                return

        raise BoxValidationError(
            "box.local.default_workspace is outside allowed_mount_roots: "
            + ", ".join(allowed_roots)
        )

    def _apply_config_to_backends(self, config: dict) -> None:
        """Apply configuration sections to corresponding backends."""
        for backend in self.backends:
            if backend is None:
                continue
            backend_config = config.get(backend.name, {})
            if backend_config and hasattr(backend, "configure"):
                backend.configure(backend_config)

    async def execute(self, spec: BoxSpec) -> BoxExecutionResult:
        if not spec.cmd:
            raise BoxValidationError("cmd must not be empty")
        session = await self._get_or_create_session(spec, track_active_exec=True)

        result: BoxExecutionResult | None = None
        cleanup_task: asyncio.Task[None] | None = None
        try:
            async with session.lock:
                if session.closing:
                    raise BoxSessionNotFoundError(
                        f"session {spec.session_id} is being deleted"
                    )
                self.logger.info(
                    "LangBot Box execute: "
                    f"session_id={spec.session_id} "
                    f"backend_session_id={session.info.backend_session_id} "
                    f"backend={session.info.backend_name} "
                    f"workdir={spec.workdir} "
                    f"timeout_sec={spec.timeout_sec}"
                )
                result = await (await self._get_backend()).exec(session.info, spec)
            return result
        finally:
            async with self._lock:
                now = dt.datetime.now(_UTC)
                if spec.session_id in self._sessions:
                    self._sessions[spec.session_id].info.last_used_at = now

                remaining = self._active_exec_counts.get(spec.session_id, 0) - 1
                if remaining > 0:
                    self._active_exec_counts[spec.session_id] = remaining
                else:
                    self._active_exec_counts.pop(spec.session_id, None)

                if result is not None and result.status == BoxExecutionStatus.TIMED_OUT:
                    cleanup_task = self._drop_session_locked(spec.session_id)
            if cleanup_task is not None:
                await self._wait_for_session_cleanup(spec.session_id, cleanup_task)

    def start_background_reaper(self) -> None:
        if self.session_ttl_sec <= 0:
            return
        if self._reaper_task is not None and not self._reaper_task.done():
            return
        self._reaper_task = asyncio.create_task(self._reaper_loop())

    async def stop_background_reaper(self) -> None:
        task = self._reaper_task
        self._reaper_task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _reaper_loop(self) -> None:
        while self.session_ttl_sec > 0:
            await asyncio.sleep(min(_REAPER_INTERVAL_SEC, self.session_ttl_sec))
            try:
                cleanup_tasks: list[asyncio.Task[None]]
                async with self._lock:
                    cleanup_tasks = await self._reap_expired_sessions_locked()
                await self._wait_for_session_cleanups(cleanup_tasks)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.warning(
                    f"LangBot Box background reaper failed: {exc}", exc_info=True
                )

    async def shutdown(self):
        self._shutdown_in_progress = True
        try:
            while True:
                async with self._lock:
                    creating = [
                        task
                        for task in self._creating_session_tasks.values()
                        if task is not asyncio.current_task()
                    ]
                if not creating:
                    break
                await asyncio.gather(*creating, return_exceptions=True)

            async with self._lock:
                cleanup_tasks = list(self._closing_session_tasks.values())
                for session_id in list(self._sessions):
                    cleanup_task = self._drop_session_locked(session_id)
                    if cleanup_task is not None:
                        cleanup_tasks.append(cleanup_task)
            await self._wait_for_session_cleanups(cleanup_tasks)

            tasks = list(self._background_tasks)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._background_tasks.clear()
        finally:
            self._shutdown_in_progress = False

    async def create_session(self, spec: BoxSpec) -> dict:
        session = await self._get_or_create_session(spec)
        return self._session_to_dict(session.info)

    async def delete_session(self, session_id: str) -> None:
        # Serialize against a session that is still being created. Otherwise a
        # delete can return "not found" while start_session is in flight and
        # leave the just-created backend resource alive.
        operation_lock = await self._get_session_operation_lock(session_id)
        async with operation_lock:
            cleanup_task: asyncio.Task[None] | None
            async with self._lock:
                cleanup_task = self._closing_session_tasks.get(session_id)
                if cleanup_task is None and session_id not in self._sessions:
                    raise BoxSessionNotFoundError(f"session {session_id} not found")
                if cleanup_task is None:
                    cleanup_task = self._drop_session_locked(session_id)
            if cleanup_task is not None:
                await self._wait_for_session_cleanup(session_id, cleanup_task)

    async def start_managed_process(
        self, session_id: str, spec: BoxManagedProcessSpec
    ) -> dict:
        async with self._lock:
            runtime_session = self._sessions.get(session_id)
            if runtime_session is None:
                raise BoxSessionNotFoundError(f"session {session_id} not found")

        async with runtime_session.lock:
            process_id = spec.process_id
            async with self._lock:
                self._reap_completed_processes()
                if (
                    runtime_session.closing
                    or self._sessions.get(session_id) is not runtime_session
                ):
                    raise BoxSessionNotFoundError(
                        f"session {session_id} is being deleted"
                    )
                running = sum(
                    1
                    for session in self._sessions.values()
                    for managed_id, managed in session.managed_processes.items()
                    if managed.is_running
                    and not (session is runtime_session and managed_id == process_id)
                )
                if running + self._managed_starting_count >= self.max_managed_processes:
                    raise BoxCapacityExceededError(
                        "Box managed process capacity reached "
                        f"({self.max_managed_processes})"
                    )
                self._managed_starting_count += 1
            try:
                existing = runtime_session.managed_processes.get(process_id)
                if existing is not None and existing.is_running:
                    # A reconnect may legitimately replace the old generation.
                    self.logger.info(
                        "LangBot Box terminating stale managed process before restart: "
                        f"session_id={session_id} process_id={process_id}"
                    )
                    await self._terminate_managed_process(existing)
                    del runtime_session.managed_processes[process_id]

                backend = await self._get_backend()
                process = await backend.start_managed_process(
                    runtime_session.info, spec
                )
            finally:
                async with self._lock:
                    self._managed_starting_count -= 1
            managed_process = _ManagedProcess(
                spec=spec,
                process=process,
                started_at=dt.datetime.now(_UTC),
                attach_lock=asyncio.Lock(),
                stderr_chunks=collections.deque(),
            )
            runtime_session.managed_processes[process_id] = managed_process
            runtime_session.info.last_used_at = dt.datetime.now(_UTC)
            self._track_background_task(
                asyncio.create_task(
                    self._drain_managed_process_stderr(
                        runtime_session.info.session_id, process_id, managed_process
                    )
                )
            )
            self._track_background_task(
                asyncio.create_task(
                    self._watch_managed_process(
                        runtime_session.info.session_id, process_id, managed_process
                    )
                )
            )
            return self._managed_process_to_dict(
                runtime_session.info.session_id, process_id, managed_process
            )

    def get_managed_process(self, session_id: str, process_id: str = "default") -> dict:
        runtime_session = self._sessions.get(session_id)
        if runtime_session is None:
            raise BoxSessionNotFoundError(f"session {session_id} not found")
        managed_process = runtime_session.managed_processes.get(process_id)
        if managed_process is None:
            raise BoxManagedProcessNotFoundError(
                f"session {session_id} has no managed process with process_id={process_id}"
            )
        return self._managed_process_to_dict(session_id, process_id, managed_process)

    async def stop_managed_process(
        self, session_id: str, process_id: str = "default"
    ) -> None:
        runtime_session = self._sessions.get(session_id)
        if runtime_session is None:
            raise BoxSessionNotFoundError(f"session {session_id} not found")

        async with runtime_session.lock:
            managed_process = runtime_session.managed_processes.pop(process_id, None)
            if managed_process is None:
                raise BoxManagedProcessNotFoundError(
                    f"session {session_id} has no managed process with process_id={process_id}"
                )
            await self._terminate_managed_process(managed_process)
            runtime_session.info.last_used_at = dt.datetime.now(_UTC)
            self.logger.info(
                f"LangBot Box managed process stopped: session_id={session_id} process_id={process_id}"
            )

    # ── Observability ─────────────────────────────────────────────────

    async def get_backend_info(self) -> dict:
        if self._backend is None:
            async with self._backend_lock:
                if self._backend is None:
                    self._backend = await self._select_backend()
        backend = self._backend
        if backend is None:
            return {"name": None, "available": False}
        try:
            available = await backend.is_available()
        except Exception:
            available = False
        return {"name": backend.name, "available": available}

    def get_sessions(self) -> list[dict]:
        return [self._session_to_dict(s.info) for s in self._sessions.values()]

    def get_session(self, session_id: str) -> dict:
        runtime_session = self._sessions.get(session_id)
        if runtime_session is None:
            raise BoxSessionNotFoundError(f"session {session_id} not found")
        result = self._session_to_dict(runtime_session.info)
        if runtime_session.managed_processes:
            managed_processes = {
                pid: self._managed_process_to_dict(session_id, pid, mp)
                for pid, mp in runtime_session.managed_processes.items()
            }
            result["managed_processes"] = managed_processes
            if "default" in managed_processes:
                result["managed_process"] = managed_processes["default"]
        return result

    async def get_status(self) -> dict:
        backend_info = await self.get_backend_info()
        return {
            "backend": backend_info,
            "active_sessions": len(self._sessions),
            "managed_processes": sum(
                1
                for runtime_session in self._sessions.values()
                for mp in runtime_session.managed_processes.values()
                if mp.is_running
            ),
            "session_ttl_sec": self.session_ttl_sec,
            "limits": {
                "max_sessions": self.max_sessions,
                "max_managed_processes": self.max_managed_processes,
                "max_completed_processes": self.max_completed_processes,
            },
        }

    async def _get_or_create_session(
        self, spec: BoxSpec, *, track_active_exec: bool = False
    ) -> _RuntimeSession:
        new_extra_mounts_key = _compute_extra_mounts_key(spec)
        operation_lock = await self._get_session_operation_lock(spec.session_id)

        async with operation_lock:
            while True:
                cleanup_task: asyncio.Task[None] | None = None
                existing: _RuntimeSession | None = None
                async with self._lock:
                    if self._shutdown_in_progress:
                        raise BoxRuntimeUnavailableError("Box runtime is shutting down")
                    await self._reap_expired_sessions_locked()
                    cleanup_task = self._closing_session_tasks.get(spec.session_id)
                    if cleanup_task is None:
                        existing = self._sessions.get(spec.session_id)
                        if existing is not None:
                            self._assert_session_compatible(existing.info, spec)
                            if existing.extra_mounts_key != new_extra_mounts_key:
                                self.logger.info(
                                    "LangBot Box session extra_mounts changed, "
                                    f"recreating: session_id={spec.session_id}"
                                )
                                cleanup_task = self._drop_session_locked(
                                    spec.session_id
                                )
                                existing = None
                            else:
                                self._session_leases[spec.session_id] += 1

                if cleanup_task is not None:
                    await self._wait_for_session_cleanup(spec.session_id, cleanup_task)
                    continue

                backend = await self._get_backend()
                if existing is not None:
                    try:
                        try:
                            alive = await backend.is_session_alive(existing.info)
                        except Exception as exc:
                            alive = False
                            self.logger.warning(
                                "LangBot Box session liveness probe failed: "
                                f"session_id={spec.session_id} error={exc}"
                            )
                    finally:
                        async with self._lock:
                            self._session_leases[spec.session_id] -= 1
                            if self._session_leases[spec.session_id] <= 0:
                                self._session_leases.pop(spec.session_id, None)

                    async with self._lock:
                        current = self._sessions.get(spec.session_id)
                        if current is existing and not existing.closing and alive:
                            existing.info.last_used_at = dt.datetime.now(_UTC)
                            if track_active_exec:
                                self._active_exec_counts[spec.session_id] += 1
                            self.logger.info(
                                "LangBot Box session reused: "
                                f"session_id={spec.session_id} "
                                f"backend_session_id={existing.info.backend_session_id} "
                                f"backend={existing.info.backend_name}"
                            )
                            return existing
                        if current is existing:
                            self.logger.warning(
                                "LangBot Box session backend disappeared, "
                                f"recreating: session_id={spec.session_id}"
                            )
                            cleanup_task = self._drop_session_locked(spec.session_id)
                        else:
                            cleanup_task = self._closing_session_tasks.get(
                                spec.session_id
                            )
                    if cleanup_task is not None:
                        await self._wait_for_session_cleanup(
                            spec.session_id, cleanup_task
                        )
                    continue

                async with self._lock:
                    if (
                        len(self._sessions)
                        + len(self._creating_session_tasks)
                        + len(self._closing_session_tasks)
                        >= self.max_sessions
                    ):
                        raise BoxCapacityExceededError(
                            f"Box session capacity reached ({self.max_sessions})"
                        )
                    current_task = asyncio.current_task()
                    if current_task is not None:
                        self._creating_session_tasks[spec.session_id] = current_task

                info: BoxSessionInfo | None = None
                try:
                    info = await backend.start_session(spec)
                    runtime_session = _RuntimeSession(
                        info=info,
                        lock=asyncio.Lock(),
                        extra_mounts_key=new_extra_mounts_key,
                    )
                    async with self._lock:
                        if self._shutdown_in_progress:
                            runtime_session.closing = True
                        else:
                            self._sessions[spec.session_id] = runtime_session
                            if track_active_exec:
                                self._active_exec_counts[spec.session_id] += 1
                    if runtime_session.closing:
                        await backend.stop_session(info)
                        raise BoxRuntimeUnavailableError("Box runtime is shutting down")
                finally:
                    async with self._lock:
                        if (
                            self._creating_session_tasks.get(spec.session_id)
                            is asyncio.current_task()
                        ):
                            self._creating_session_tasks.pop(spec.session_id, None)

                self.logger.info(
                    "LangBot Box session created: "
                    f"session_id={spec.session_id} "
                    f"backend_session_id={info.backend_session_id} "
                    f"backend={info.backend_name} image={info.image} "
                    f"network={info.network.value} host_path={info.host_path} "
                    f"host_path_mode={info.host_path_mode.value} "
                    f"mount_path={info.mount_path} "
                    f"workspace_quota_mb={info.workspace_quota_mb}"
                )
                return runtime_session

    async def _get_session_operation_lock(self, session_id: str) -> asyncio.Lock:
        async with self._lock:
            lock = self._session_operation_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_operation_locks[session_id] = lock
            return lock

    async def _get_backend(self) -> BaseSandboxBackend:
        if self._backend is None:
            async with self._backend_lock:
                if self._backend is None:
                    self._backend = await self._select_backend()
        if self._backend is None:
            raise BoxBackendUnavailableError(
                "LangBot Box backend unavailable. Install and start Docker or nsjail before using exec."
            )
        return self._backend

    # Backends grouped under each top-level box.backend choice.
    # 'local' picks the first available local container backend (docker → nsjail).
    _LOCAL_BACKEND_NAMES = ("docker", "nsjail")

    async def _select_backend(self) -> BaseSandboxBackend | None:
        # Backend selection comes from box.backend only.
        # Accepted values: 'local', 'docker', 'nsjail', 'e2b'. 'local' fans out
        # to local container backends; everything else must match one backend exactly.
        forced = (self._box_config.get("backend") or "").strip()
        source_label = "box.backend"

        candidates: list[BaseSandboxBackend]
        if forced == "local":
            candidates = [
                b
                for b in self.backends
                if b is not None and b.name in self._LOCAL_BACKEND_NAMES
            ]
            if not candidates:
                self.logger.error(
                    f"LangBot Box: no local backend registered "
                    f"({source_label}={forced})"
                )
                return None
        elif forced:
            candidates = [
                b for b in self.backends if b is not None and b.name == forced
            ]
            if not candidates:
                available_names = [b.name for b in self.backends if b is not None]
                self.logger.error(
                    f'LangBot Box backend "{forced}" not found '
                    f"({source_label}={forced}, available: {available_names})"
                )
                return None
        else:
            candidates = [b for b in self.backends if b is not None]

        for backend in candidates:
            try:
                await backend.initialize()
                if await backend.is_available():
                    label = (
                        f"{backend.name} (forced via {source_label}={forced})"
                        if forced
                        else backend.name
                    )
                    self.logger.info(f"LangBot Box using backend: {label}")
                    return backend
            except Exception as exc:
                self.logger.warning(
                    f"LangBot Box backend {backend.name} probe failed: {exc}"
                )

        if forced:
            self.logger.error(
                f'LangBot Box backend "{forced}" probed but not available '
                f"({source_label}={forced})"
            )

        self.logger.warning(
            "LangBot Box backend unavailable: no supported backend (Docker, nsjail, E2B) is ready"
        )
        return None

    async def _reap_expired_sessions_locked(self) -> list[asyncio.Task[None]]:
        self._reap_completed_processes()
        if self.session_ttl_sec <= 0:
            return []

        deadline = dt.datetime.now(_UTC) - dt.timedelta(seconds=self.session_ttl_sec)
        expired_session_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if not session.info.persistent
            and session.info.last_used_at < deadline
            and self._active_exec_counts.get(session_id, 0) <= 0
            and self._session_leases.get(session_id, 0) <= 0
            and not any(mp.is_running for mp in session.managed_processes.values())
        ]

        cleanup_tasks: list[asyncio.Task[None]] = []
        for session_id in expired_session_ids:
            cleanup_task = self._drop_session_locked(session_id)
            if cleanup_task is not None:
                cleanup_tasks.append(cleanup_task)
        return cleanup_tasks

    def _reap_completed_processes(self) -> None:
        """Bound retained diagnostics without one sleeping task per process."""
        now = dt.datetime.now(_UTC)
        deadline = now - dt.timedelta(seconds=self.completed_process_retention_sec)
        completed: list[tuple[dt.datetime, _RuntimeSession, str, _ManagedProcess]] = []
        for session in self._sessions.values():
            for process_id, managed_process in list(session.managed_processes.items()):
                if managed_process.is_running or managed_process.exited_at is None:
                    continue
                if (
                    self.completed_process_retention_sec <= 0
                    or managed_process.exited_at <= deadline
                ):
                    if session.managed_processes.get(process_id) is managed_process:
                        session.managed_processes.pop(process_id, None)
                    continue
                completed.append(
                    (
                        managed_process.exited_at,
                        session,
                        process_id,
                        managed_process,
                    )
                )

        overflow = len(completed) - max(self.max_completed_processes, 0)
        if overflow <= 0:
            return
        for _, session, process_id, managed_process in sorted(
            completed, key=lambda item: item[0]
        )[:overflow]:
            if session.managed_processes.get(process_id) is managed_process:
                session.managed_processes.pop(process_id, None)

    def _drop_session_locked(self, session_id: str) -> asyncio.Task[None] | None:
        closing_task = self._closing_session_tasks.get(session_id)
        if closing_task is not None:
            return closing_task

        runtime_session = self._sessions.pop(session_id, None)
        if runtime_session is not None:
            runtime_session.closing = True
        self._active_exec_counts.pop(session_id, None)
        backend = self._backend
        if runtime_session is None or backend is None:
            return None

        cleanup_task = asyncio.create_task(
            self._cleanup_session_resources(session_id, runtime_session, backend)
        )
        self._closing_session_tasks[session_id] = cleanup_task
        return cleanup_task

    async def _cleanup_session_resources(
        self,
        session_id: str,
        runtime_session: _RuntimeSession,
        backend: BaseSandboxBackend,
    ) -> None:
        try:
            async with runtime_session.lock:
                for mp in list(runtime_session.managed_processes.values()):
                    await self._terminate_managed_process(mp)
                runtime_session.managed_processes.clear()

                try:
                    self.logger.info(
                        "LangBot Box session cleanup: "
                        f"session_id={session_id} "
                        f"backend_session_id={runtime_session.info.backend_session_id} "
                        f"backend={runtime_session.info.backend_name}"
                    )
                    await backend.stop_session(runtime_session.info)
                except Exception as exc:
                    self.logger.warning(
                        f"Failed to clean up box session {session_id}: {exc}"
                    )
        except Exception as exc:
            self.logger.warning(
                f"Failed to finalize box session cleanup {session_id}: {exc}",
                exc_info=True,
            )
        finally:
            current_task = asyncio.current_task()
            async with self._lock:
                if self._closing_session_tasks.get(session_id) is current_task:
                    self._closing_session_tasks.pop(session_id, None)

    async def _wait_for_session_cleanups(
        self, cleanup_tasks: list[asyncio.Task[None]]
    ) -> None:
        for cleanup_task in cleanup_tasks:
            await self._wait_for_session_cleanup(None, cleanup_task)

    async def _wait_for_session_cleanup(
        self, session_id: str | None, cleanup_task: asyncio.Task[None]
    ) -> None:
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            label = f" {session_id}" if session_id is not None else ""
            self.logger.warning(
                f"LangBot Box session cleanup task failed{label}: {exc}",
                exc_info=True,
            )

    def _assert_session_compatible(self, session: BoxSessionInfo, spec: BoxSpec):
        _COMPAT_FIELDS = (
            "network",
            "image",
            "host_path",
            "host_path_mode",
            "mount_path",
            "persistent",
            "cpus",
            "memory_mb",
            "pids_limit",
            "read_only_rootfs",
            "workspace_quota_mb",
        )
        for field in _COMPAT_FIELDS:
            session_val = getattr(session, field)
            spec_val = getattr(spec, field)
            if session_val != spec_val:
                display = (
                    session_val.value if hasattr(session_val, "value") else session_val
                )
                raise BoxSessionConflictError(
                    f"Box session {spec.session_id} already exists with {field}={display}"
                )

    async def _drain_managed_process_stderr(
        self, session_id: str, process_id: str, managed_process: _ManagedProcess
    ) -> None:
        stream = managed_process.process.stderr
        if stream is None:
            return

        try:
            while True:
                chunk = await stream.readline()
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                managed_process.stderr_chunks.append(text)
                managed_process.stderr_total_len += (
                    len(text) + 1
                )  # +1 for '\n' separator
                while (
                    managed_process.stderr_total_len
                    > _MANAGED_PROCESS_STDERR_PREVIEW_LIMIT
                    and managed_process.stderr_chunks
                ):
                    removed = managed_process.stderr_chunks.popleft()
                    managed_process.stderr_total_len -= len(removed) + 1
                self.logger.info(
                    f"LangBot Box managed process stderr: session_id={session_id} process_id={process_id} {text}"
                )
        except Exception as exc:
            self.logger.warning(
                f"Failed to drain managed process stderr for {session_id}/{process_id}: {exc}"
            )

    async def _watch_managed_process(
        self, session_id: str, process_id: str, managed_process: _ManagedProcess
    ) -> None:
        return_code = await managed_process.process.wait()
        managed_process.exit_code = return_code
        managed_process.exited_at = dt.datetime.now(_UTC)
        runtime_session = self._sessions.get(session_id)
        if runtime_session is not None:
            runtime_session.info.last_used_at = managed_process.exited_at
        self.logger.info(
            f"LangBot Box managed process exited: session_id={session_id} process_id={process_id} return_code={return_code}"
        )
        # Retention is reaped synchronously from the in-memory registry. This
        # avoids accumulating one five-minute sleeping task for every short-
        # lived process while still preserving bounded exit diagnostics.
        self._reap_completed_processes()

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _terminate_managed_process(
        self, managed_process: _ManagedProcess
    ) -> None:
        if not managed_process.is_running:
            return

        process = managed_process.process
        try:
            if process.stdin is not None:
                process.stdin.close()
        except Exception:
            pass

        try:
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
            await asyncio.wait_for(asyncio.shield(process.wait()), timeout=5)
        except asyncio.TimeoutError:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
        finally:
            managed_process.exit_code = process.returncode
            managed_process.exited_at = dt.datetime.now(_UTC)

    def _managed_process_to_dict(
        self, session_id: str, process_id: str, managed_process: _ManagedProcess
    ) -> dict:
        stderr_preview = "\n".join(managed_process.stderr_chunks)
        status = (
            BoxManagedProcessStatus.RUNNING
            if managed_process.is_running
            else BoxManagedProcessStatus.EXITED
        )
        return BoxManagedProcessInfo(
            session_id=session_id,
            process_id=process_id,
            status=status,
            command=managed_process.spec.command,
            args=managed_process.spec.args,
            cwd=managed_process.spec.cwd,
            env_keys=sorted(managed_process.spec.env.keys()),
            attached=managed_process.attach_lock.locked(),
            started_at=managed_process.started_at,
            exited_at=managed_process.exited_at,
            exit_code=managed_process.exit_code,
            stderr_preview=stderr_preview,
        ).model_dump(mode="json")

    @staticmethod
    def _session_to_dict(info: BoxSessionInfo) -> dict:
        return info.model_dump(mode="json")
