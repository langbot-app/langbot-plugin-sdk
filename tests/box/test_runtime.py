"""Unit tests for the BoxRuntime session manager.

These tests inject a fake backend implementing the ``BaseSandboxBackend``
interface, so they exercise the real ``BoxRuntime`` logic (config handling,
session create/reuse, compatibility checks, expiry/reaping, execute flow,
status, backend selection) without Docker, nsjail, or E2B.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from unittest import mock

import pytest

from langbot_plugin.box.backend import BaseSandboxBackend
from langbot_plugin.box.errors import (
    BoxBackendUnavailableError,
    BoxManagedProcessNotFoundError,
    BoxSessionConflictError,
    BoxSessionNotFoundError,
    BoxValidationError,
)
from langbot_plugin.box.models import (
    BoxExecutionResult,
    BoxExecutionStatus,
    BoxManagedProcessSpec,
    BoxManagedProcessStatus,
    BoxSessionInfo,
    BoxSpec,
)
from langbot_plugin.box.runtime import BoxRuntime

_UTC = dt.timezone.utc


@pytest.fixture
def logger():
    return logging.getLogger("test.box.runtime")


class FakeBackend(BaseSandboxBackend):
    """Fake backend with AsyncMock-style hooks for BoxRuntime tests.

    Each created session gets a unique ``backend_session_id`` so reuse vs
    recreate can be asserted by inspecting returned info.
    """

    def __init__(
        self,
        logger: logging.Logger,
        name: str = "fake",
        available: bool = True,
    ):
        super().__init__(logger)
        self.name = name
        self._available = available
        self._alive = True
        self.started_sessions = 0
        self.stopped_sessions = 0
        self.exec_calls: list[tuple[str, str]] = []
        # Result returned by exec(); overridable per-test.
        self.exec_status = BoxExecutionStatus.COMPLETED
        self.exec_exit_code: int | None = 0
        self.initialize_calls = 0
        # Wrap call-tracked methods in AsyncMock so tests can assert on them.
        # These shadow the concrete class-level methods defined below (which
        # satisfy the ABC's abstractmethod requirement at class definition).
        self.is_available = mock.AsyncMock(side_effect=self._is_available)
        self.is_session_alive = mock.AsyncMock(side_effect=self._is_session_alive)
        self.stop_session = mock.AsyncMock(side_effect=self._stop_session)

    async def initialize(self):
        self.initialize_calls += 1

    # Concrete class-level implementations of the abstract methods so the
    # class is instantiable. Instances replace these with AsyncMocks (above)
    # that delegate to the matching ``_`` helpers.
    async def is_available(self) -> bool:
        return await self._is_available()

    async def stop_session(self, session: BoxSessionInfo):
        await self._stop_session(session)

    async def _is_available(self) -> bool:
        return self._available

    async def start_session(self, spec: BoxSpec) -> BoxSessionInfo:
        self.started_sessions += 1
        now = dt.datetime.now(_UTC)
        return BoxSessionInfo(
            session_id=spec.session_id,
            backend_name=self.name,
            backend_session_id=f"{self.name}-{self.started_sessions}",
            image=spec.image,
            network=spec.network,
            host_path=spec.host_path,
            host_path_mode=spec.host_path_mode,
            mount_path=spec.mount_path,
            persistent=spec.persistent,
            cpus=spec.cpus,
            memory_mb=spec.memory_mb,
            pids_limit=spec.pids_limit,
            read_only_rootfs=spec.read_only_rootfs,
            workspace_quota_mb=spec.workspace_quota_mb,
            created_at=now,
            last_used_at=now,
        )

    async def exec(self, session: BoxSessionInfo, spec: BoxSpec) -> BoxExecutionResult:
        self.exec_calls.append((session.backend_session_id, spec.cmd))
        return BoxExecutionResult(
            session_id=session.session_id,
            backend_name=self.name,
            status=self.exec_status,
            exit_code=self.exec_exit_code,
            stdout="hello",
            stderr="",
            duration_ms=12,
        )

    async def _stop_session(self, session: BoxSessionInfo):
        self.stopped_sessions += 1

    async def _is_session_alive(self, session: BoxSessionInfo) -> bool:
        return self._alive

    async def start_managed_process(self, session: BoxSessionInfo, spec):
        proc = FakeProcess()
        self.last_process = proc
        return proc


class FakeProcess:
    """Minimal stand-in for asyncio.subprocess.Process.

    ``wait()`` blocks until ``finish()`` is called, so ``is_running`` stays
    True while the managed process is "running" in a test.
    """

    def __init__(self):
        self.returncode: int | None = None
        self._done = asyncio.Event()
        self.stdin = mock.Mock()
        self.stdout = None
        # No stderr stream → the drain task returns immediately.
        self.stderr = None
        self.terminate = mock.Mock(side_effect=self._terminate)
        self.kill = mock.Mock(side_effect=self._kill)

    def _terminate(self):
        # Emulate the process exiting on SIGTERM.
        self.returncode = -15
        self._done.set()

    def _kill(self):
        self.returncode = -9
        self._done.set()

    def finish(self, code: int = 0):
        self.returncode = code
        self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        return self.returncode if self.returncode is not None else 0


def _make_spec(session_id: str = "s1", **kwargs) -> BoxSpec:
    base = {"session_id": session_id, "cmd": "echo hi", "read_only_rootfs": False}
    base.update(kwargs)
    return BoxSpec(**base)


# ── construction / config handling ─────────────────────────────────────


def test_init_without_env_config_has_empty_box_config(logger):
    """No LANGBOT_BOX_CONFIG → empty parsed config."""
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[FakeBackend(logger)])
    assert runtime._box_config == {}
    assert runtime.session_ttl_sec == 300
    assert len(runtime.instance_id) == 12


def test_init_reads_langbot_box_config_env(logger):
    """LANGBOT_BOX_CONFIG env JSON is parsed into _box_config."""
    payload = {"backend": "fake", "fake": {"foo": "bar"}}
    with mock.patch("os.getenv", return_value=json.dumps(payload)):
        runtime = BoxRuntime(logger, backends=[FakeBackend(logger)])
    assert runtime._box_config == payload


def test_init_invalid_env_config_is_ignored(logger):
    """Malformed LANGBOT_BOX_CONFIG JSON is swallowed (warning) → empty config."""
    with mock.patch("os.getenv", return_value="{not valid json"):
        runtime = BoxRuntime(logger, backends=[FakeBackend(logger)])
    assert runtime._box_config == {}


def test_init_method_applies_config_and_resets_backend(logger):
    """init() merges config, applies to backends, resets backend when idle."""
    backend = FakeBackend(logger, name="fake")
    backend.configure = mock.Mock()
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
    runtime._backend = backend  # pretend already selected

    runtime.init({"backend": "fake", "fake": {"cpus": 2}})

    assert runtime._box_config["backend"] == "fake"
    backend.configure.assert_called_once_with({"cpus": 2})
    # No active sessions → backend reset so it re-selects with new config.
    assert runtime._backend is None


@pytest.mark.anyio
async def test_init_method_keeps_backend_when_sessions_exist(logger):
    """init() must NOT reset backend while sessions are live."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("keep"))
    runtime.init({"backend": "fake"})
    assert runtime._backend is backend


@pytest.mark.anyio
async def test_initialize_applies_config_selects_and_cleans_orphans(logger):
    """initialize() applies env config, selects backend, sets instance_id, cleans orphans."""
    backend = FakeBackend(logger, name="fake")
    backend.configure = mock.Mock()
    backend.cleanup_orphaned_containers = mock.AsyncMock()
    cfg = json.dumps({"backend": "fake", "fake": {"cpus": 1}})
    with mock.patch("os.getenv", return_value=cfg):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.initialize()

    assert runtime._backend is backend
    backend.configure.assert_called_once_with({"cpus": 1})
    assert backend.instance_id == runtime.instance_id
    backend.cleanup_orphaned_containers.assert_awaited_once_with(runtime.instance_id)


@pytest.mark.anyio
async def test_initialize_orphan_cleanup_failure_is_swallowed(logger):
    """A failing orphan cleanup must not raise out of initialize()."""
    backend = FakeBackend(logger)
    backend.cleanup_orphaned_containers = mock.AsyncMock(
        side_effect=RuntimeError("boom")
    )
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.initialize()  # should not raise
    assert runtime._backend is backend


# ── _get_or_create_session: create vs reuse ─────────────────────────────


@pytest.mark.anyio
async def test_create_session_creates_new(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        info = await runtime.create_session(_make_spec("alpha"))

    assert backend.started_sessions == 1
    assert info["session_id"] == "alpha"
    assert info["backend_session_id"] == "fake-1"
    assert len(runtime._sessions) == 1


@pytest.mark.anyio
async def test_create_session_reuses_existing(logger):
    """Same session_id + compatible spec reuses the live session."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        first = await runtime.create_session(_make_spec("beta"))
        second = await runtime.create_session(_make_spec("beta"))

    assert backend.started_sessions == 1  # not started again
    assert first["backend_session_id"] == second["backend_session_id"] == "fake-1"
    backend.is_session_alive.assert_awaited()  # liveness checked on reuse


@pytest.mark.anyio
async def test_reuse_recreates_when_backend_session_dead(logger):
    """If backend reports the session is dead, it is dropped and recreated."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        first = await runtime.create_session(_make_spec("gamma"))
        backend._alive = False
        second = await runtime.create_session(_make_spec("gamma"))

    assert first["backend_session_id"] == "fake-1"
    assert second["backend_session_id"] == "fake-2"
    assert backend.started_sessions == 2
    assert backend.stopped_sessions == 1


# ── _assert_session_compatible across _COMPAT_FIELDS ────────────────────


@pytest.mark.anyio
@pytest.mark.parametrize(
    "field,changed",
    [
        ("image", "other/image:latest"),
        ("memory_mb", 1024),
        ("cpus", 2.0),
        ("pids_limit", 64),
        ("workspace_quota_mb", 50),
        ("persistent", True),
    ],
)
async def test_incompatible_reuse_raises_conflict(logger, field, changed):
    """Reusing a session_id with a differing _COMPAT_FIELD raises conflict."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("delta"))
        with pytest.raises(BoxSessionConflictError) as exc_info:
            await runtime.create_session(_make_spec("delta", **{field: changed}))

    assert field in str(exc_info.value)
    # Conflict means we did not start a second backend session.
    assert backend.started_sessions == 1


@pytest.mark.anyio
async def test_compatible_reuse_does_not_raise(logger):
    """Differing-but-non-compat field (e.g. cmd/timeout) still reuses."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("eps", cmd="echo a", timeout_sec=10))
        info = await runtime.create_session(
            _make_spec("eps", cmd="echo b", timeout_sec=99)
        )
    assert info["backend_session_id"] == "fake-1"
    assert backend.started_sessions == 1


# ── execute flow ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_execute_empty_cmd_raises(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        with pytest.raises(BoxValidationError):
            await runtime.execute(_make_spec("z", cmd=""))


@pytest.mark.anyio
async def test_execute_creates_session_and_runs(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        result = await runtime.execute(_make_spec("run1", cmd="echo hi"))

    assert isinstance(result, BoxExecutionResult)
    assert result.status == BoxExecutionStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert backend.started_sessions == 1
    assert backend.exec_calls == [("fake-1", "echo hi")]
    assert len(runtime._sessions) == 1


@pytest.mark.anyio
async def test_execute_updates_last_used_at(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("run2"))
        before = runtime._sessions["run2"].info.last_used_at
        await runtime.execute(_make_spec("run2", cmd="echo hi"))
        after = runtime._sessions["run2"].info.last_used_at
    assert after >= before


@pytest.mark.anyio
async def test_execute_timeout_drops_session(logger):
    """A TIMED_OUT result triggers the session to be dropped & backend stopped."""
    backend = FakeBackend(logger)
    backend.exec_status = BoxExecutionStatus.TIMED_OUT
    backend.exec_exit_code = None
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        result = await runtime.execute(_make_spec("to", cmd="sleep 999"))

    assert result.status == BoxExecutionStatus.TIMED_OUT
    assert "to" not in runtime._sessions
    backend.stop_session.assert_awaited_once()


# ── session expiry / reaping ────────────────────────────────────────────


@pytest.mark.anyio
async def test_reap_expired_sessions(logger):
    """Sessions idle past TTL are reaped on the next create/exec under lock."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend], session_ttl_sec=60)
        await runtime.create_session(_make_spec("old"))
        # Force the session to look stale.
        stale = dt.datetime.now(_UTC) - dt.timedelta(seconds=120)
        runtime._sessions["old"].info.last_used_at = stale

        # Touching another session triggers reaping of expired ones.
        await runtime.create_session(_make_spec("fresh"))

    assert "old" not in runtime._sessions
    assert "fresh" in runtime._sessions
    backend.stop_session.assert_awaited_once()


@pytest.mark.anyio
async def test_reap_skips_persistent_sessions(logger):
    """Persistent sessions are never reaped even when idle."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend], session_ttl_sec=60)
        await runtime.create_session(_make_spec("keep", persistent=True))
        runtime._sessions["keep"].info.last_used_at = dt.datetime.now(
            _UTC
        ) - dt.timedelta(seconds=999)
        async with runtime._lock:
            await runtime._reap_expired_sessions_locked()

    assert "keep" in runtime._sessions
    backend.stop_session.assert_not_awaited()


@pytest.mark.anyio
async def test_reap_disabled_when_ttl_non_positive(logger):
    """ttl <= 0 disables reaping entirely."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend], session_ttl_sec=0)
        await runtime.create_session(_make_spec("immortal"))
        runtime._sessions["immortal"].info.last_used_at = dt.datetime.now(
            _UTC
        ) - dt.timedelta(days=7)
        async with runtime._lock:
            await runtime._reap_expired_sessions_locked()

    assert "immortal" in runtime._sessions
    backend.stop_session.assert_not_awaited()


# ── delete_session / shutdown ───────────────────────────────────────────


@pytest.mark.anyio
async def test_delete_unknown_session_raises(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        with pytest.raises(BoxSessionNotFoundError):
            await runtime.delete_session("nope")


@pytest.mark.anyio
async def test_delete_session_stops_backend(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("del"))
        await runtime.delete_session("del")

    assert "del" not in runtime._sessions
    backend.stop_session.assert_awaited_once()


@pytest.mark.anyio
async def test_shutdown_drops_non_persistent_keeps_persistent(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("ephemeral"))
        await runtime.create_session(_make_spec("persist", persistent=True))
        await runtime.shutdown()

    assert "ephemeral" not in runtime._sessions
    assert "persist" in runtime._sessions
    assert backend.stopped_sessions == 1


# ── get_status / get_backend_info / get_session(s) ──────────────────────


@pytest.mark.anyio
async def test_get_status_reports_sessions_and_ttl(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend], session_ttl_sec=42)
        await runtime.create_session(_make_spec("a"))
        await runtime.create_session(_make_spec("b"))
        status = await runtime.get_status()

    assert status["active_sessions"] == 2
    assert status["session_ttl_sec"] == 42
    assert status["managed_processes"] == 0
    assert status["backend"] == {"name": "fake", "available": True}


@pytest.mark.anyio
async def test_get_backend_info_unavailable(logger):
    """is_available raising → reported as unavailable."""
    backend = FakeBackend(logger)
    backend.is_available = mock.AsyncMock(side_effect=RuntimeError("probe failed"))
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        runtime._backend = backend
        info = await runtime.get_backend_info()
    assert info == {"name": "fake", "available": False}


@pytest.mark.anyio
async def test_get_backend_info_none_when_no_backend(logger):
    """All backends unavailable → backend info reports name None / not available."""
    backend = FakeBackend(logger, available=False)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        info = await runtime.get_backend_info()
    assert info == {"name": None, "available": False}


@pytest.mark.anyio
async def test_get_sessions_and_get_session(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("one"))
        sessions = runtime.get_sessions()
        single = runtime.get_session("one")

    assert len(sessions) == 1
    assert single["session_id"] == "one"
    assert "managed_processes" not in single  # none started


def test_get_session_unknown_raises(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        with pytest.raises(BoxSessionNotFoundError):
            runtime.get_session("ghost")


# ── _get_backend / backend selection ────────────────────────────────────


@pytest.mark.anyio
async def test_get_backend_selects_first_available(logger):
    unavailable = FakeBackend(logger, name="fake", available=False)
    available = FakeBackend(logger, name="other", available=True)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[unavailable, available])
        selected = await runtime._get_backend()
    assert selected is available


@pytest.mark.anyio
async def test_get_backend_raises_when_none_available(logger):
    backend = FakeBackend(logger, available=False)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        with pytest.raises(BoxBackendUnavailableError):
            await runtime._get_backend()


@pytest.mark.anyio
async def test_get_backend_caches_selection(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        first = await runtime._get_backend()
        second = await runtime._get_backend()
    assert first is second is backend
    # initialize() only runs during the first selection.
    assert backend.initialize_calls == 1


@pytest.mark.anyio
async def test_select_backend_forced_local_picks_local_name(logger):
    """box.backend=local fans out to local container backends."""
    nsjail = FakeBackend(logger, name="nsjail", available=True)
    e2b = FakeBackend(logger, name="e2b", available=True)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[e2b, nsjail])
        runtime.init({"backend": "local"})
        selected = await runtime._select_backend()
    assert selected is nsjail


@pytest.mark.anyio
async def test_select_backend_forced_local_no_local_returns_none(logger):
    e2b = FakeBackend(logger, name="e2b", available=True)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[e2b])
        runtime.init({"backend": "local"})
        selected = await runtime._select_backend()
    assert selected is None


@pytest.mark.anyio
async def test_select_backend_probe_exception_skips_backend(logger):
    """A backend whose probe raises is skipped in favour of the next one."""
    bad = FakeBackend(logger, name="bad", available=True)
    bad.is_available = mock.AsyncMock(side_effect=RuntimeError("probe blew up"))
    good = FakeBackend(logger, name="good", available=True)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[bad, good])
        selected = await runtime._select_backend()
    assert selected is good


# ── managed processes ───────────────────────────────────────────────────


async def _settle():
    """Yield control so background tasks (drain/watch) get a chance to run."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.anyio
async def test_start_managed_process_creates_and_reports_running(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("mp"))
        info = await runtime.start_managed_process(
            "mp", BoxManagedProcessSpec(command="sleep", args=["1"])
        )
        await _settle()

        assert info["session_id"] == "mp"
        assert info["process_id"] == "default"
        assert info["status"] == BoxManagedProcessStatus.RUNNING.value

        # get_managed_process returns the same view.
        got = runtime.get_managed_process("mp", "default")
        assert got["command"] == "sleep"
        assert got["args"] == ["1"]

        # get_session surfaces the managed process.
        session = runtime.get_session("mp")
        assert "managed_processes" in session
        assert "managed_process" in session  # 'default' alias
        assert session["managed_process"]["status"] == (
            BoxManagedProcessStatus.RUNNING.value
        )

        # get_status counts the running managed process.
        status = await runtime.get_status()
        assert status["managed_processes"] == 1

        # Clean up: stop the process and its background tasks.
        await runtime.stop_managed_process("mp", "default")


@pytest.mark.anyio
async def test_start_managed_process_unknown_session_raises(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        with pytest.raises(BoxSessionNotFoundError):
            await runtime.start_managed_process(
                "ghost", BoxManagedProcessSpec(command="sleep")
            )


@pytest.mark.anyio
async def test_start_managed_process_replaces_running_one(logger):
    """Starting a process when one is already running terminates the old one."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("mp2"))
        await runtime.start_managed_process(
            "mp2", BoxManagedProcessSpec(command="first")
        )
        await _settle()
        first_proc = backend.last_process

        await runtime.start_managed_process(
            "mp2", BoxManagedProcessSpec(command="second")
        )
        await _settle()

        # The stale process was terminated before the new one started.
        assert first_proc.returncode is not None
        got = runtime.get_managed_process("mp2", "default")
        assert got["command"] == "second"

        await runtime.stop_managed_process("mp2", "default")


@pytest.mark.anyio
async def test_get_managed_process_not_found_raises(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("mp3"))
        with pytest.raises(BoxManagedProcessNotFoundError):
            runtime.get_managed_process("mp3", "default")


def test_get_managed_process_unknown_session_raises(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        with pytest.raises(BoxSessionNotFoundError):
            runtime.get_managed_process("ghost", "default")


@pytest.mark.anyio
async def test_stop_managed_process_terminates_and_marks_exited(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("mp4"))
        await runtime.start_managed_process(
            "mp4", BoxManagedProcessSpec(command="daemon")
        )
        await _settle()
        proc = backend.last_process

        await runtime.stop_managed_process("mp4", "default")

        assert proc.returncode is not None
        # The process entry was removed from the session.
        with pytest.raises(BoxManagedProcessNotFoundError):
            runtime.get_managed_process("mp4", "default")


@pytest.mark.anyio
async def test_stop_managed_process_unknown_raises(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("mp5"))
        with pytest.raises(BoxManagedProcessNotFoundError):
            await runtime.stop_managed_process("mp5", "default")


@pytest.mark.anyio
async def test_stop_managed_process_unknown_session_raises(logger):
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        with pytest.raises(BoxSessionNotFoundError):
            await runtime.stop_managed_process("ghost", "default")


@pytest.mark.anyio
async def test_watch_managed_process_marks_exit_on_natural_finish(logger):
    """When the underlying process exits, the watcher records the exit code."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend])
        await runtime.create_session(_make_spec("mp6"))
        await runtime.start_managed_process(
            "mp6", BoxManagedProcessSpec(command="quickexit")
        )
        await _settle()

        proc = backend.last_process
        proc.finish(code=3)
        await _settle()

        got = runtime.get_managed_process("mp6", "default")
        assert got["status"] == BoxManagedProcessStatus.EXITED.value
        assert got["exit_code"] == 3


@pytest.mark.anyio
async def test_reap_skips_session_with_running_managed_process(logger):
    """An idle session is NOT reaped while it has a running managed process."""
    backend = FakeBackend(logger)
    with mock.patch("os.getenv", return_value=""):
        runtime = BoxRuntime(logger, backends=[backend], session_ttl_sec=60)
        await runtime.create_session(_make_spec("mp7"))
        await runtime.start_managed_process(
            "mp7", BoxManagedProcessSpec(command="daemon")
        )
        await _settle()
        runtime._sessions["mp7"].info.last_used_at = dt.datetime.now(
            _UTC
        ) - dt.timedelta(seconds=999)

        async with runtime._lock:
            await runtime._reap_expired_sessions_locked()

        assert "mp7" in runtime._sessions  # protected by running process
        await runtime.stop_managed_process("mp7", "default")
