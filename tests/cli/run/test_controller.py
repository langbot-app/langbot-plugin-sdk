from __future__ import annotations

from typing import Any

import pytest

from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.definition.plugin import BasePlugin, NonePlugin
from langbot_plugin.api.entities.builtin.provider import session as provider_session
from langbot_plugin.cli.run.controller import PluginRuntimeController
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


def test_controller_builds_unmounted_placeholder_container():
    controller = _controller()

    assert controller._stdio is True
    assert controller.ws_debug_url == "ws://runtime/plugin/ws"
    assert controller.plugin_container.status is RuntimeContainerStatus.UNMOUNTED
    assert isinstance(controller.plugin_container.plugin_instance, NonePlugin)
    assert [component.manifest.kind for component in controller.plugin_container.components] == [
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

    await controller.initialize(
        {"enabled": True, "priority": 0, "plugin_config": {}}
    )
    await controller.cleanup_instances()

    assert isinstance(controller.plugin_container.plugin_instance, NonePlugin)
    assert controller.plugin_container.status is RuntimeContainerStatus.UNMOUNTED
    assert all(
        isinstance(component.component_instance, NoneComponent)
        for component in controller.plugin_container.components
    )
