from __future__ import annotations

import argparse
import asyncio

from langbot_plugin.runtime import app as runtime_app


class FakePluginManager:
    instances = []

    def __init__(self, context):
        self.context = context
        self.wait_for_control_connection = None
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


class FakeServerController:
    instances = []

    def __init__(self, port=None):
        self.port = port
        self.callbacks = []
        self.instances.append(self)

    async def run(self, callback):
        self.callbacks.append(callback)
        await callback(object())


class FakeControlHandler:
    instances = []

    def __init__(self, connection, context):
        self.connection = connection
        self.context = context
        self.calls = []
        self.instances.append(self)

    async def run(self):
        self.calls.append("run")


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
    assert app.context.ws_debug_server.port == 5501


async def test_set_control_handler_runs_handler_and_resolves_waiter(monkeypatch):
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
    app.context.plugin_mgr.wait_for_control_connection = asyncio.Future()
    handler = FakeControlHandler(object(), app.context)

    task = app.set_control_handler(handler)
    await task

    assert app.context.control_handler is handler
    assert handler.calls == ["run"]
    assert app.context.plugin_mgr.wait_for_control_connection is None


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

    await app.run()

    manager = FakePluginManager.instances[-1]
    assert manager.calls == [
        "ensure_deps",
        "add_plugin_handler",
        "launch_all",
    ]
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
    app = runtime_app.RuntimeApplication(
        _args(skip_deps_check=True, debug_only=True)
    )

    await app.run()

    assert FakePluginManager.instances[-1].calls == ["add_plugin_handler"]


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

    await app.run()

    assert app.context.ws_control_server.callbacks
    assert FakeControlHandler.instances[-1].calls == ["run"]
    assert FakePluginManager.instances[-1].calls == ["add_plugin_handler"]


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

    monkeypatch.setattr(
        runtime_app,
        "configure_process_logging",
        lambda: calls.append(("configure_logging",)),
    )
    monkeypatch.setattr(runtime_app, "RuntimeApplication", FakeApplication)

    runtime_app.main(_args())

    assert calls == [("configure_logging",), ("init", _args()), ("run",)]


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
    monkeypatch.setattr(
        runtime_app.asyncio,
        "run",
        lambda coroutine: (_ for _ in ()).throw(asyncio.CancelledError()),
    )

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
    monkeypatch.setattr(
        runtime_app.asyncio,
        "run",
        lambda coroutine: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    runtime_app.main(_args())

    assert calls == [("configure_logging",), ("init", _args())]
