from __future__ import annotations

import asyncio
import typing

from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.runtime.plugin.container import (
    ComponentContainer,
    PluginContainer,
    RuntimeContainerStatus,
)
from langbot_plugin.cli.run.handler import PluginRuntimeHandler
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.controllers.stdio import (
    server as stdio_controller_server,
)
from langbot_plugin.runtime.io.controllers.ws import (
    client as ws_controller_client,
)
from langbot_plugin.runtime.io.controller import Controller
from langbot_plugin.api.definition.base import NonePlugin, BasePlugin
from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.common.event_listener import EventListener


class PluginRuntimeController:
    """The controller for running plugins."""

    _stdio: bool
    """Check if the controller is using stdio for connection."""

    handler: PluginRuntimeHandler

    _controller_task: asyncio.Task[None]

    plugin_container: PluginContainer

    _connection_waiter: asyncio.Future[Connection]

    def __init__(
        self,
        plugin_manifest: ComponentManifest,
        component_manifests: list[ComponentManifest],
        stdio: bool,
        ws_debug_url: str,
    ) -> None:
        self._stdio = stdio
        self.ws_debug_url = ws_debug_url

        # discover components
        components_containers = [
            ComponentContainer(
                manifest=component_manifest,
                component_instance=NoneComponent(),
                component_config={},
            )
            for component_manifest in component_manifests
        ]

        self.plugin_container = PluginContainer(
            manifest=plugin_manifest,
            plugin_instance=NonePlugin(),  # will be set later
            enabled=True,
            priority=0,
            plugin_config={},
            status=RuntimeContainerStatus.UNMOUNTED,
            components=components_containers,
        )

    async def mount(self) -> None:
        print("Mounting plugin...")
        controller: Controller

        self._connection_waiter = asyncio.Future()

        async def new_connection_callback(connection: Connection):
            self.handler = PluginRuntimeHandler(connection)
            self.handler.plugin_container = self.plugin_container
            self._connection_waiter.set_result(connection)
            await self.handler.run()

        if self._stdio:
            controller = stdio_controller_server.StdioServerController()
        else:
            controller = ws_controller_client.WebSocketClientController(
                self.ws_debug_url
            )

        self._controller_task = asyncio.create_task(controller.run(new_connection_callback))

        # wait for the connection to be established
        _ = await self._connection_waiter

        # send manifest info to runtime
        plugin_settings = await self.handler.get_plugin_settings()
        self.plugin_container.enabled = plugin_settings["enabled"]
        self.plugin_container.priority = plugin_settings["priority"]
        self.plugin_container.plugin_config = plugin_settings["plugin_config"]

        self.plugin_container.status = RuntimeContainerStatus.MOUNTED

        print("Plugin mounted")

    async def initialize(self) -> None:
        print("Initializing plugin...")
        # initialize plugin instance
        plugin_cls = self.plugin_container.manifest.get_python_component_class()
        assert isinstance(plugin_cls, type(BasePlugin))
        self.plugin_container.plugin_instance = plugin_cls()
        self.plugin_container.plugin_instance.config = self.plugin_container.plugin_config
        await self.plugin_container.plugin_instance.initialize()

        # initialize event listener component
        for component_container in self.plugin_container.components:
            if component_container.manifest.kind == "EventListener":
                event_listener_cls = component_container.manifest.get_python_component_class()
                assert isinstance(event_listener_cls, type(EventListener))
                component_container.component_instance = event_listener_cls()
                component_container.component_instance.plugin_instance = self.plugin_container.plugin_instance
                await component_container.component_instance.initialize()
                break

        print("Plugin initialized")

    async def run(self) -> None:
        await self._controller_task

# {"seq_id": 1, "code": 0, "data": {"enabled": true, "priority": 0, "plugin_config": {}}}