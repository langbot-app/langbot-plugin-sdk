from __future__ import annotations

import asyncio
import os
import typing
import logging

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
from langbot_plugin.api.definition.plugin import NonePlugin, BasePlugin
from langbot_plugin.api.definition.components.base import NoneComponent, BaseComponent
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.definition.components.command.command import Command
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.entities.io.errors import ConnectionClosedError

logger = logging.getLogger(__name__)


class PluginRuntimeController:
    """The controller for running plugins."""

    _stdio: bool
    """Check if the controller is using stdio for connection."""

    handler: PluginRuntimeHandler

    _controller_task: asyncio.Task[None]

    plugin_container: PluginContainer

    _connection_waiter: asyncio.Future[Connection]

    prod_mode: bool
    """Mark this process as production plugin process, only used on Windows"""

    def __init__(
        self,
        plugin_manifest: ComponentManifest,
        component_manifests: list[ComponentManifest],
        stdio: bool,
        ws_debug_url: str,
        prod_mode: bool = False,
    ) -> None:
        self._stdio = stdio
        self.ws_debug_url = ws_debug_url
        self.prod_mode = prod_mode
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

    async def run(self) -> None:
        await self._controller_task

    async def mount(self) -> None:
        logger.info(f"Mounting plugin {self.plugin_container.manifest.metadata.author}/{self.plugin_container.manifest.metadata.name}...")
        controller: Controller

        self._connection_waiter = asyncio.Future()

        async def new_connection_callback(connection: Connection):
            self.handler = PluginRuntimeHandler(connection, self.initialize)

            async def disconnect_callback(hdl: PluginRuntimeHandler):
                os._exit(0)

            self.handler.set_disconnect_callback(disconnect_callback)
            self.handler.plugin_container = self.plugin_container
            self._connection_waiter.set_result(connection)
            await self.handler.run()

        async def make_connection_failed_callback(controller: Controller, e: Exception = None):
            logger.error(f"Connection failed to {self.plugin_container.manifest.metadata.author}/{self.plugin_container.manifest.metadata.name}, exit")
            self._connection_waiter.set_exception(
                ConnectionClosedError(f"Connection failed: {e}")
            )
            exit(1)

        if self._stdio:
            controller = stdio_controller_server.StdioServerController()
        else:
            controller = ws_controller_client.WebSocketClientController(
                self.ws_debug_url, make_connection_failed_callback
            )

        self._controller_task = asyncio.create_task(
            controller.run(new_connection_callback)
        )

        # wait for the connection to be established
        _ = await self._connection_waiter

        # send manifest info to runtime
        self.plugin_container.status = RuntimeContainerStatus.MOUNTED

        logger.info(f"Plugin {self.plugin_container.manifest.metadata.author}/{self.plugin_container.manifest.metadata.name} mounted")

        # register plugin
        await self.handler.register_plugin(prod_mode=self.prod_mode)

    async def initialize(self, plugin_settings: dict[str, typing.Any]) -> None:
        logger.info(f"Initializing plugin {self.plugin_container.manifest.metadata.author}/{self.plugin_container.manifest.metadata.name}...")
        logger.debug(f"plugin_settings: {plugin_settings}")

        self.plugin_container.enabled = plugin_settings["enabled"]
        self.plugin_container.priority = plugin_settings["priority"]
        self.plugin_container.plugin_config = plugin_settings["plugin_config"]
        # initialize plugin instance
        plugin_cls = self.plugin_container.manifest.get_python_component_class()
        assert isinstance(plugin_cls, type(BasePlugin))
        self.plugin_container.plugin_instance = plugin_cls()
        self.plugin_container.plugin_instance.config = (
            self.plugin_container.plugin_config
        )
        self.plugin_container.plugin_instance.plugin_runtime_handler = self.handler
        await self.plugin_container.plugin_instance.initialize()

        preinitialize_component_classes: list[type[BaseComponent]] = [
            EventListener,
            Tool,
            Command,
        ]

        for component_cls in preinitialize_component_classes:
            for component_container in self.plugin_container.components:
                if component_container.manifest.kind == component_cls.__kind__:
                    component_impl_cls = (
                        component_container.manifest.get_python_component_class()
                    )
                    assert issubclass(component_impl_cls, component_cls)
                    component_container.component_instance = component_impl_cls()
                    component_container.component_instance.plugin = (
                        self.plugin_container.plugin_instance
                    )
                    await component_container.component_instance.initialize()

        logger.info(f"Plugin {self.plugin_container.manifest.metadata.author}/{self.plugin_container.manifest.metadata.name} initialized")

        self.plugin_container.status = RuntimeContainerStatus.INITIALIZED


# {"seq_id": 1, "code": 0, "data": {"enabled": true, "priority": 0, "plugin_config": {}}}
