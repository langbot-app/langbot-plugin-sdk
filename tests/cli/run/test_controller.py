from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.definition.plugin import BasePlugin, NonePlugin
from langbot_plugin.api.entities.builtin.provider import session as provider_session
from langbot_plugin.cli.run import controller as controller_module
from langbot_plugin.cli.run.controller import PluginRuntimeController
from langbot_plugin.entities.io.errors import ConnectionClosedError
from langbot_plugin.runtime.plugin.container import RuntimeContainerStatus


class DemoPlugin(BasePlugin):
    initialized = False

    async def initialize(self) -> None:
        self.initialized = True


class DemoTool(Tool):
    initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        return "ok"


class DemoEventListener(EventListener):
    initialized = False

    async def initialize(self) -> None:
        self.initialized = True


def _manifest(kind: str, name: str) -> ComponentManifest:
    return ComponentManifest(
        owner="tester",
        rel_path=f"{name}.yaml",
        manifest={
            "apiVersion": "v1",
            "kind": kind,
            "metadata": {
                "name": name,
                "label": {"en_US": name.title()},
                "author": "tester",
                "version": "1.0.0",
            },
            "spec": {},
            "execution": {"python": {"path": f"./{name}.py", "attr": name.title()}},
        },
    )


def _controller() -> PluginRuntimeController:
    return PluginRuntimeController(
        plugin_manifest=_manifest("Plugin", "demo"),
        component_manifests=[
            _manifest("Tool", "lookup"),
            _manifest("EventListener", "events"),
            _manifest("UnknownKind", "unknown"),
        ],
        stdio=True,
        ws_debug_url="ws://runtime/plugin/ws",
    )


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.closed_event = asyncio.Event()

    async def send(self, message: str) -> None:
        pass

    async def receive(self) -> str:
        await asyncio.Future()

    async def close(self) -> None:
        self.closed = True
        self.closed_event.set()


class FakeHotReloader:
    instances: list["FakeHotReloader"] = []

    def __init__(self, watch_path, on_reload_callback):
        self.watch_path = watch_path
        self.on_reload_callback = on_reload_callback
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _fake_handler_class(*, run_forever: bool = False):
    instances = []

    class FakePluginRuntimeHandler:
        def __init__(self, connection, initialize_callback):
            self.connection = connection
            self.initialize_callback = initialize_callback
            self.disconnect_callback = None
            self.shutdown_callback = None
            self.plugin_container = None
            self.register_calls = []
            self.run_started = asyncio.Event()
            self.registered = asyncio.Event()
            self.cancelled = asyncio.Event()
            instances.append(self)

        def set_disconnect_callback(self, callback):
            self.disconnect_callback = callback

        async def run(self):
            self.run_started.set()
            if not run_forever:
                return

            try:
                await asyncio.Future()
            finally:
                self.cancelled.set()

        async def register_plugin(self, prod_mode: bool = False):
            self.register_calls.append(prod_mode)
            self.registered.set()
            return {"ok": True}

        async def get_plugin_container(self):
            return {
                "enabled": True,
                "priority": 7,
                "plugin_config": {"mode": "debug"},
            }

    FakePluginRuntimeHandler.instances = instances
    return FakePluginRuntimeHandler


def _install_stdio_controller(monkeypatch, *behaviors: str):
    controllers = []

    class FakeStdioServerController:
        def __init__(self):
            self.index = len(controllers)
            self.connection = FakeConnection()
            controllers.append(self)

        async def run(self, new_connection_callback):
            behavior = behaviors[self.index] if self.index < len(behaviors) else "wait"
            if behavior == "connect":
                await new_connection_callback(self.connection)
                return
            if behavior == "wait":
                await asyncio.Future()
                return
            raise AssertionError(f"Unknown fake controller behavior: {behavior}")

    monkeypatch.setattr(
        controller_module.stdio_controller_server,
        "StdioServerController",
        FakeStdioServerController,
    )
    return controllers


def _install_ws_failure_controller(monkeypatch, failure: Exception):
    controllers = []

    class FakeWebSocketClientController:
        def __init__(self, ws_url, make_connection_failed_callback):
            self.ws_url = ws_url
            self.make_connection_failed_callback = make_connection_failed_callback
            controllers.append(self)

        async def run(self, new_connection_callback):
            await self.make_connection_failed_callback(self, failure)

    monkeypatch.setattr(
        controller_module.ws_controller_client,
        "WebSocketClientController",
        FakeWebSocketClientController,
    )
    return controllers


async def _wait_until(predicate, timeout: float = 1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Timed out waiting for predicate")


def test_controller_builds_unmounted_placeholder_container():
    controller = _controller()

    assert controller._stdio is True
    assert controller.ws_debug_url == "ws://runtime/plugin/ws"
    assert controller.plugin_container.status is RuntimeContainerStatus.UNMOUNTED
    assert isinstance(controller.plugin_container.plugin_instance, NonePlugin)
    assert [
        component.manifest.kind for component in controller.plugin_container.components
    ] == [
        "Tool",
        "EventListener",
        "UnknownKind",
    ]
    assert all(
        isinstance(component.component_instance, NoneComponent)
        for component in controller.plugin_container.components
    )


@pytest.mark.asyncio
async def test_initialize_creates_plugin_and_supported_component_instances(monkeypatch):
    controller = _controller()
    controller.handler = object()
    component_classes = {
        "Plugin": DemoPlugin,
        "Tool": DemoTool,
        "EventListener": DemoEventListener,
    }

    def fake_component_class(self: ComponentManifest):
        return component_classes[self.kind]

    monkeypatch.setattr(
        ComponentManifest,
        "get_python_component_class",
        fake_component_class,
    )

    await controller.initialize(
        {
            "enabled": False,
            "priority": 42,
            "plugin_config": {"token": "secret"},
        }
    )

    plugin = controller.plugin_container.plugin_instance
    assert isinstance(plugin, DemoPlugin)
    assert plugin.initialized is True
    assert plugin.config == {"token": "secret"}
    assert plugin.plugin_runtime_handler is controller.handler
    assert controller.plugin_container.enabled is False
    assert controller.plugin_container.priority == 42
    assert controller.plugin_container.status is RuntimeContainerStatus.INITIALIZED

    tool, event_listener, unknown = controller.plugin_container.components
    assert isinstance(tool.component_instance, DemoTool)
    assert tool.component_instance.initialized is True
    assert tool.component_instance.plugin is plugin
    assert isinstance(event_listener.component_instance, DemoEventListener)
    assert event_listener.component_instance.initialized is True
    assert event_listener.component_instance.plugin is plugin
    assert isinstance(unknown.component_instance, NoneComponent)


@pytest.mark.asyncio
async def test_cleanup_instances_resets_runtime_objects(monkeypatch):
    controller = _controller()
    controller.handler = object()

    component_classes = {
        "Plugin": DemoPlugin,
        "Tool": DemoTool,
        "EventListener": DemoEventListener,
    }

    def fake_component_class(self: ComponentManifest):
        return component_classes[self.kind]

    monkeypatch.setattr(
        ComponentManifest,
        "get_python_component_class",
        fake_component_class,
    )

    await controller.initialize({"enabled": True, "priority": 0, "plugin_config": {}})
    await controller.cleanup_instances()

    assert isinstance(controller.plugin_container.plugin_instance, NonePlugin)
    assert controller.plugin_container.status is RuntimeContainerStatus.UNMOUNTED
    assert all(
        isinstance(component.component_instance, NoneComponent)
        for component in controller.plugin_container.components
    )


@pytest.mark.asyncio
async def test_mount_stdio_prod_registers_plugin(monkeypatch):
    fake_handler_cls = _fake_handler_class()
    monkeypatch.setattr(controller_module, "PluginRuntimeHandler", fake_handler_cls)
    controllers = _install_stdio_controller(monkeypatch, "connect")
    controller = PluginRuntimeController(
        plugin_manifest=_manifest("Plugin", "demo"),
        component_manifests=[],
        stdio=True,
        ws_debug_url="ws://runtime/plugin/ws",
        prod_mode=True,
    )

    await controller.mount()

    assert len(controllers) == 1
    handler = fake_handler_cls.instances[0]
    assert handler.plugin_container is controller.plugin_container
    assert handler.register_calls == [True]
    assert controller.plugin_container.status is RuntimeContainerStatus.MOUNTED


@pytest.mark.asyncio
async def test_mount_prod_connection_failure_sets_waiter_and_exits(monkeypatch):
    controller = PluginRuntimeController(
        plugin_manifest=_manifest("Plugin", "demo"),
        component_manifests=[],
        stdio=False,
        ws_debug_url="ws://runtime/plugin/ws",
        prod_mode=True,
    )
    controllers = _install_ws_failure_controller(monkeypatch, RuntimeError("boom"))
    exit_calls = []

    def fake_exit(code):
        exit_calls.append(code)

    monkeypatch.setattr(controller_module, "exit", fake_exit, raising=False)

    with pytest.raises(ConnectionClosedError, match="Connection failed: boom"):
        await controller.mount()

    assert controllers[0].ws_url == "ws://runtime/plugin/ws"
    assert exit_calls == [1]
    assert controller._connection_waiter.done()


@pytest.mark.asyncio
async def test_mount_debug_connection_failure_sets_waiter_exception_without_exit(
    monkeypatch,
):
    class StopMount(Exception):
        pass

    controller = PluginRuntimeController(
        plugin_manifest=_manifest("Plugin", "demo"),
        component_manifests=[],
        stdio=False,
        ws_debug_url="ws://runtime/plugin/ws",
        prod_mode=False,
    )
    FakeHotReloader.instances = []
    monkeypatch.setattr(controller_module, "HotReloader", FakeHotReloader)
    _install_ws_failure_controller(monkeypatch, RuntimeError("boom"))

    def fail_exit(code):
        raise AssertionError(f"debug mode should not exit with {code}")

    async def stop_on_retry(delay):
        assert delay == 3
        raise StopMount

    monkeypatch.setattr(controller_module, "exit", fail_exit, raising=False)
    monkeypatch.setattr(controller_module.asyncio, "sleep", stop_on_retry)

    with pytest.raises(StopMount):
        await controller.mount()

    assert controller._connection_waiter.done()
    with pytest.raises(ConnectionClosedError, match="Connection failed: boom"):
        controller._connection_waiter.result()
    assert FakeHotReloader.instances[0].started is True
    assert FakeHotReloader.instances[0].stopped is True


@pytest.mark.asyncio
async def test_mount_debug_shutdown_callback_closes_connection_and_reconnects(
    monkeypatch,
):
    fake_handler_cls = _fake_handler_class(run_forever=True)
    monkeypatch.setattr(controller_module, "PluginRuntimeHandler", fake_handler_cls)
    FakeHotReloader.instances = []
    monkeypatch.setattr(controller_module, "HotReloader", FakeHotReloader)
    controllers = _install_stdio_controller(monkeypatch, "connect", "wait")
    controller = _controller()

    mount_task = asyncio.create_task(controller.mount())
    await _wait_until(lambda: len(fake_handler_cls.instances) == 1)
    handler = fake_handler_cls.instances[0]
    await asyncio.wait_for(handler.registered.wait(), timeout=1)

    assert handler.shutdown_callback is not None
    await handler.shutdown_callback()

    await asyncio.wait_for(controllers[0].connection.closed_event.wait(), timeout=1)
    await asyncio.wait_for(handler.cancelled.wait(), timeout=1)
    await _wait_until(
        lambda: controller.plugin_container.status is RuntimeContainerStatus.UNMOUNTED
    )

    mount_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await mount_task
    if hasattr(controller, "_controller_task"):
        controller._controller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await controller._controller_task

    assert len(controllers) == 2
    assert FakeHotReloader.instances[0].started is True
    assert FakeHotReloader.instances[0].stopped is True


@pytest.mark.asyncio
async def test_mount_hot_reload_callback_reinitializes_current_settings(
    monkeypatch,
    tmp_path,
):
    controller = _controller()
    controller.handler = _fake_handler_class()(
        FakeConnection(),
        controller.initialize,
    )
    cleanup_calls = []
    initialize_calls = []
    reload_calls = []
    FakeHotReloader.instances = []

    async def fake_cleanup():
        cleanup_calls.append(True)

    async def fake_initialize(plugin_settings):
        initialize_calls.append(plugin_settings)

    def fake_reload_plugin_modules(path):
        reload_calls.append(path)

    monkeypatch.setattr(controller, "cleanup_instances", fake_cleanup)
    monkeypatch.setattr(controller, "initialize", fake_initialize)
    monkeypatch.setattr(
        controller_module, "reload_plugin_modules", fake_reload_plugin_modules
    )
    monkeypatch.setattr(controller_module.os, "getcwd", lambda: str(tmp_path))
    monkeypatch.setattr(controller_module, "HotReloader", FakeHotReloader)
    _install_stdio_controller(monkeypatch, "wait")

    mount_task = asyncio.create_task(controller.mount())
    await _wait_until(lambda: len(FakeHotReloader.instances) == 1)

    await FakeHotReloader.instances[0].on_reload_callback()

    assert cleanup_calls == [True]
    assert reload_calls == [str(tmp_path)]
    assert initialize_calls == [
        {
            "enabled": True,
            "priority": 7,
            "plugin_config": {"mode": "debug"},
        }
    ]

    mount_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await mount_task
    controller._controller_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await controller._controller_task
    assert FakeHotReloader.instances[0].stopped is True


@pytest.mark.asyncio
async def test_reload_and_reinitialize_cleans_instances_and_reloads_cwd(
    monkeypatch,
    tmp_path,
):
    controller = _controller()
    controller.plugin_container.plugin_instance = DemoPlugin()
    controller.plugin_container.components[0].component_instance = DemoTool()
    controller.plugin_container.status = RuntimeContainerStatus.INITIALIZED
    reload_calls = []

    monkeypatch.setattr(controller_module.os, "getcwd", lambda: str(tmp_path))
    monkeypatch.setattr(
        controller_module,
        "reload_plugin_modules",
        lambda path: reload_calls.append(path),
    )

    await controller.reload_and_reinitialize()

    assert reload_calls == [str(tmp_path)]
    assert isinstance(controller.plugin_container.plugin_instance, NonePlugin)
    assert controller.plugin_container.status is RuntimeContainerStatus.UNMOUNTED
    assert all(
        isinstance(component.component_instance, NoneComponent)
        for component in controller.plugin_container.components
    )
