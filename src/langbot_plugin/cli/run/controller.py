from __future__ import annotations

import asyncio
import typing

from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.runtime.plugin.container import (
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


class PluginRuntimeController:
    """The controller for running plugins."""

    _stdio: bool
    """Check if the controller is using stdio for connection."""

    handler: PluginRuntimeHandler | None = None

    plugin_container: PluginContainer

    _connection_waiter: asyncio.Future[Connection]

    def __init__(
        self,
        plugin_manifest: ComponentManifest,
        stdio: bool,
        ws_debug_url: str,
    ) -> None:
        self._stdio = stdio
        self.ws_debug_url = ws_debug_url
        self.plugin_container = PluginContainer(
            manifest=plugin_manifest,
            plugin_instance=None,
            enabled=True,
            priority=0,
            plugin_config={},
            status=RuntimeContainerStatus.UNMOUNTED,
            components=[],
        )

    async def initialize(self) -> None:
        controller: Controller

        self._connection_waiter = asyncio.Future()

        async def new_connection_callback(connection: Connection):
            self.handler = PluginRuntimeHandler(connection)
            self._connection_waiter.set_result(connection)
            await self.handler.run()

        if self._stdio:
            controller = stdio_controller_server.StdioServerController()
        else:
            controller = ws_controller_client.WebSocketClientController(
                self.ws_debug_url
            )

        asyncio.create_task(controller.run(new_connection_callback))

        # wait for the connection to be established
        _ = await self._connection_waiter

    async def mount(self) -> None:
        pass

    async def run(self) -> None:
        pass
