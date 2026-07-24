from __future__ import annotations

import argparse
import asyncio
import signal

import pytest

from langbot_plugin.runtime import app as runtime_app
from langbot_plugin.runtime.security import (
    PLUGIN_DEBUG_KEY_HEADER,
    PLUGIN_REGISTRATION_CAPABILITY_HEADER,
    PLUGIN_RUNTIME_CONTROL_TOKEN_ENV,
    PLUGIN_RUNTIME_CONTROL_TOKEN_HEADER,
)
from langbot_plugin.entities.io.context import (
    PluginWorkerPolicy,
    RuntimeIdentity,
)


class FakePluginManager:
    instances = []

    def __init__(self, context):
        self.context = context
        self.calls = []
        self.handlers = []
        self.instances.append(self)

    async def ensure_all_plugins_dependencies_installed(self):
        self.calls.append("ensure_deps")

    async def launch_all_plugins(self):
        self.calls.append("launch_all")

    async def add_plugin_handler(self, handler):
        self.calls.append("add_plugin_handler")
        self.handlers.append(handler)

    async def shutdown_all_plugins(self):
        self.calls.append("shutdown_all")

    def mark_control_connection_ready(self):
        self.calls.append("control_ready")

    def is_registration_capability_pending(self, capability):
        return capability == "pending-registration-capability"


class FakeServerController:
    instances = []

    def __init__(self, port=None, **kwargs):
        self.port = port
        self.kwargs = kwargs
        self.callbacks = []
        self.instances.append(self)

    async def run(self, callback):
        self.callbacks.append(callback)
        await callback(object())


class FailingServerController(FakeServerController):
    async def run(self, callback):
        raise RuntimeError("listener bind failed")


class FakeControlHandler:
    instances = []

    def __init__(self, connection, context):
        self.connection = connection
        self.conn = connection
        self.context = context
        self.calls = []
        self.invalidated = False
        self.instances.append(self)

    async def run(self):
        self.calls.append("run")

    async def close(self):
        close = getattr(self.connection, "close", None)
        if close is not None:
            await close()

    def invalidate(self):
        self.invalidated = True


class FakeConnection:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakePluginHandler:
    instances = []

    def __init__(self, connection, context, debug_plugin=False):
        self.connection = connection
        self.context = context
        self.debug_plugin = debug_plugin
        self.instances.append(self)


def _args(**overrides):
    defaults = {
        "pypi_index_url": "",
        "pypi_trusted_host": "",
        "ws_debug_port": 5401,
        "stdio_control": True,
        "ws_control_port": 5400,
        "skip_deps_check": False,
        "debug_only": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _configure_runtime(app, profile="oss_dev"):
    app.context.bind_runtime(
        RuntimeIdentity(instance_uuid="instance-a", runtime_id="runtime-a"),
        PluginWorkerPolicy(
            max_cpus=1.0,
            max_memory_mb=512,
            max_pids=128,
            max_open_files=256,
            max_file_size_mb=512,
        ),
        profile,
    )


@pytest.fixture(autouse=True)
def _runtime_secrets(monkeypatch):
    monkeypatch.setattr(runtime_app.settings, "plugin_debug_key", "")
    monkeypatch.setenv(PLUGIN_RUNTIME_CONTROL_TOKEN_ENV, "c" * 48)


def test_runtime_application_initializes_stdio_control_mode(monkeypatch):
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )

    app = runtime_app.RuntimeApplication(
        _args(
            stdio_control=True,
            pypi_index_url="https://mirror",
            pypi_trusted_host="mirror",
        )
    )

    assert app._control_connection_mode is runtime_app.ControlConnectionMode.STDIO
    assert isinstance(app.context.stdio_server, FakeServerController)
    assert app.context.ws_control_server is None
    assert app.context.ws_debug_server.port == 5401
    assert len(runtime_app.settings.plugin_debug_key) >= 32
    authenticator = app.context.ws_debug_server.kwargs["request_authenticator"]
    assert authenticator(
        {PLUGIN_DEBUG_KEY_HEADER: runtime_app.settings.plugin_debug_key}
    )
    assert authenticator(
        {PLUGIN_REGISTRATION_CAPABILITY_HEADER: ("pending-registration-capability")}
    )
    assert not authenticator({PLUGIN_DEBUG_KEY_HEADER: "wrong"})
    assert app.context.ws_debug_port == 5401
    assert runtime_app.os.environ["LANGBOT_PLUGIN_PYPI_INDEX_URL"] == "https://mirror"
    assert runtime_app.os.environ["LANGBOT_PLUGIN_PYPI_TRUSTED_HOST"] == "mirror"


def test_runtime_application_initializes_websocket_control_mode(monkeypatch):
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )

    app = runtime_app.RuntimeApplication(
        _args(stdio_control=False, ws_control_port=5500, ws_debug_port=5501)
    )

    assert app._control_connection_mode is runtime_app.ControlConnectionMode.WS
    assert app.context.stdio_server is None
    assert app.context.ws_control_server.port == 5500
    assert app.context.ws_control_server.kwargs["expected_headers"] == {
        PLUGIN_RUNTIME_CONTROL_TOKEN_HEADER: "c" * 48,
    }
    assert app.context.ws_debug_server.port == 5501


def test_runtime_application_rejects_websocket_control_without_secret(monkeypatch):
    monkeypatch.setattr(runtime_app.plugin_mgr_cls, "PluginManager", FakePluginManager)
    monkeypatch.delenv(PLUGIN_RUNTIME_CONTROL_TOKEN_ENV)

    with pytest.raises(ValueError, match=PLUGIN_RUNTIME_CONTROL_TOKEN_ENV):
        runtime_app.RuntimeApplication(_args(stdio_control=False))


def test_runtime_application_rejects_weak_configured_debug_key(monkeypatch):
    monkeypatch.setattr(runtime_app.plugin_mgr_cls, "PluginManager", FakePluginManager)
    monkeypatch.setattr(runtime_app.settings, "plugin_debug_key", "short")

    with pytest.raises(ValueError, match="PLUGIN_DEBUG_KEY"):
        runtime_app.RuntimeApplication(_args(stdio_control=True))


async def test_set_control_handler_runs_handler(monkeypatch):
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )
    app = runtime_app.RuntimeApplication(_args())
    handler = FakeControlHandler(object(), app.context)

    task = app.set_control_handler(handler)
    await task

    assert app.context.control_handler is None
    assert handler.calls == ["run"]


async def test_new_control_handler_fences_and_closes_previous_handler(monkeypatch):
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )
    app = runtime_app.RuntimeApplication(_args())

    class BlockingControlHandler(FakeControlHandler):
        def __init__(self, connection, context):
            super().__init__(connection, context)
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def run(self):
            self.calls.append("run")
            self.started.set()
            await self.release.wait()

        async def close(self):
            await super().close()
            self.release.set()

    old_connection = FakeConnection()
    new_connection = FakeConnection()
    old_handler = BlockingControlHandler(old_connection, app.context)
    new_handler = BlockingControlHandler(new_connection, app.context)

    old_task = app.set_control_handler(old_handler)
    await old_handler.started.wait()
    new_task = app.set_control_handler(new_handler)
    await new_handler.started.wait()

    assert app.context.control_handler is new_handler
    assert old_handler.invalidated is True
    assert old_connection.closed is True
    assert new_handler.invalidated is False
    assert new_connection.closed is False

    new_handler.release.set()
    await new_task
    await old_task
    assert app.context.control_handler is None


async def test_runtime_application_run_coordinates_servers_and_plugin_manager(
    monkeypatch,
):
    FakePluginManager.instances = []
    FakeControlHandler.instances = []
    FakePluginHandler.instances = []
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.control_handler_cls,
        "ControlConnectionHandler",
        FakeControlHandler,
    )
    monkeypatch.setattr(
        runtime_app.plugin_handler_cls,
        "PluginConnectionHandler",
        FakePluginHandler,
    )
    app = runtime_app.RuntimeApplication(_args(stdio_control=True))
    _configure_runtime(app)

    await app.run()

    manager = FakePluginManager.instances[-1]
    assert sorted(manager.calls) == [
        "add_plugin_handler",
        "control_ready",
        "ensure_deps",
        "launch_all",
    ]
    assert manager.calls.index("ensure_deps") < manager.calls.index("launch_all")
    assert FakeControlHandler.instances[-1].calls == ["run"]
    assert FakePluginHandler.instances[-1].debug_plugin is True


async def test_runtime_application_run_can_skip_deps_and_plugin_launch(monkeypatch):
    FakePluginManager.instances = []
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.control_handler_cls,
        "ControlConnectionHandler",
        FakeControlHandler,
    )
    monkeypatch.setattr(
        runtime_app.plugin_handler_cls,
        "PluginConnectionHandler",
        FakePluginHandler,
    )
    app = runtime_app.RuntimeApplication(_args(skip_deps_check=True, debug_only=True))
    _configure_runtime(app)

    await app.run()

    assert sorted(FakePluginManager.instances[-1].calls) == [
        "add_plugin_handler",
        "control_ready",
    ]


async def test_runtime_application_surfaces_listener_failure(monkeypatch):
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FailingServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )
    app = runtime_app.RuntimeApplication(_args(skip_deps_check=True, debug_only=True))

    with pytest.raises(RuntimeError, match="listener bind failed"):
        await app.run()


async def test_runtime_application_run_uses_websocket_control_server(monkeypatch):
    FakePluginManager.instances = []
    FakeControlHandler.instances = []
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.control_handler_cls,
        "ControlConnectionHandler",
        FakeControlHandler,
    )
    monkeypatch.setattr(
        runtime_app.plugin_handler_cls,
        "PluginConnectionHandler",
        FakePluginHandler,
    )
    app = runtime_app.RuntimeApplication(
        _args(stdio_control=False, skip_deps_check=True, debug_only=True)
    )
    _configure_runtime(app)

    await app.run()

    assert app.context.ws_control_server.callbacks
    assert FakeControlHandler.instances[-1].calls == ["run"]
    assert sorted(FakePluginManager.instances[-1].calls) == [
        "add_plugin_handler",
        "control_ready",
    ]


async def test_legacy_workloads_wait_for_runtime_configuration(monkeypatch):
    FakePluginManager.instances = []
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    app = runtime_app.RuntimeApplication(_args())

    workload = asyncio.create_task(app._start_legacy_plugin_workloads())
    await asyncio.sleep(0)
    assert FakePluginManager.instances[-1].calls == []

    _configure_runtime(app)
    await workload

    assert FakePluginManager.instances[-1].calls == ["ensure_deps", "launch_all"]


async def test_shared_runtime_never_runs_legacy_plugin_workloads(monkeypatch):
    FakePluginManager.instances = []
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    app = runtime_app.RuntimeApplication(_args())
    _configure_runtime(app, "shared")

    await app._start_legacy_plugin_workloads()

    assert FakePluginManager.instances[-1].calls == []


async def test_runtime_application_shutdown_delegates_to_plugin_manager(monkeypatch):
    FakePluginManager.instances = []
    monkeypatch.setattr(
        runtime_app.plugin_mgr_cls,
        "PluginManager",
        FakePluginManager,
    )
    monkeypatch.setattr(
        runtime_app.stdio_controller_server,
        "StdioServerController",
        FakeServerController,
    )
    monkeypatch.setattr(
        runtime_app.ws_controller_server,
        "WebSocketServerController",
        FakeServerController,
    )
    app = runtime_app.RuntimeApplication(_args())

    await app.shutdown()

    assert FakePluginManager.instances[-1].calls == ["shutdown_all"]


def test_runtime_main_configures_logging_and_runs_application(monkeypatch):
    calls = []

    class FakeApplication:
        def __init__(self, args):
            calls.append(("init", args))

        async def run(self):
            calls.append(("run",))

        async def shutdown(self):
            calls.append(("shutdown",))

    monkeypatch.setattr(
        runtime_app,
        "configure_process_logging",
        lambda: calls.append(("configure_logging",)),
    )
    monkeypatch.setattr(runtime_app, "RuntimeApplication", FakeApplication)

    runtime_app.main(_args())

    assert calls == [
        ("configure_logging",),
        ("init", _args()),
        ("run",),
        ("shutdown",),
    ]


async def test_runtime_sigterm_cancels_run_and_awaits_shutdown(monkeypatch):
    callbacks = {}
    removed_signals = []
    run_started = asyncio.Event()
    shutdown_complete = asyncio.Event()
    running_loop = asyncio.get_running_loop()

    monkeypatch.setattr(
        running_loop,
        "add_signal_handler",
        lambda sig, callback: callbacks.__setitem__(sig, callback),
    )
    monkeypatch.setattr(
        running_loop,
        "remove_signal_handler",
        lambda sig: removed_signals.append(sig) or True,
    )

    class FakeApplication:
        async def run(self):
            run_started.set()
            callbacks[signal.SIGTERM]()
            await asyncio.Event().wait()

        async def shutdown(self):
            shutdown_complete.set()

    with pytest.raises(asyncio.CancelledError):
        await runtime_app._run_with_shutdown(FakeApplication())

    assert run_started.is_set()
    assert shutdown_complete.is_set()
    assert removed_signals == [signal.SIGTERM]


def test_runtime_main_handles_cancelled_error(monkeypatch):
    calls = []

    class FakeApplication:
        def __init__(self, args):
            calls.append(("init", args))

        def run(self):
            return "coroutine"

    monkeypatch.setattr(
        runtime_app,
        "configure_process_logging",
        lambda: calls.append(("configure_logging",)),
    )
    monkeypatch.setattr(runtime_app, "RuntimeApplication", FakeApplication)

    def cancel_run(coroutine):
        coroutine.close()
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime_app.asyncio, "run", cancel_run)

    runtime_app.main(_args())

    assert calls == [("configure_logging",), ("init", _args())]


def test_runtime_main_handles_keyboard_interrupt(monkeypatch):
    calls = []

    class FakeApplication:
        def __init__(self, args):
            calls.append(("init", args))

        def run(self):
            return "coroutine"

    monkeypatch.setattr(
        runtime_app,
        "configure_process_logging",
        lambda: calls.append(("configure_logging",)),
    )
    monkeypatch.setattr(runtime_app, "RuntimeApplication", FakeApplication)

    def interrupt_run(coroutine):
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(runtime_app.asyncio, "run", interrupt_run)

    runtime_app.main(_args())

    assert calls == [("configure_logging",), ("init", _args())]
