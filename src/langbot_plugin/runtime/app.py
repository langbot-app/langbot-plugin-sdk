from __future__ import annotations

import argparse
from enum import Enum
import signal
import logging

import asyncio

from langbot_plugin.runtime.io.controllers.stdio import (
    server as stdio_controller_server,
)
from langbot_plugin.runtime.io.controllers.ws import server as ws_controller_server
from langbot_plugin.runtime.io.handlers import control as control_handler_cls
from langbot_plugin.runtime.io.handlers import plugin as plugin_handler_cls
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.plugin import mgr as plugin_mgr_cls
from langbot_plugin.runtime import context
from langbot_plugin.runtime.settings import settings

logger = logging.getLogger(__name__)


class ControlConnectionMode(Enum):
    STDIO = "stdio"
    WS = "ws"


class RuntimeApplication:
    """Runtime application context."""

    _control_connection_mode: ControlConnectionMode

    context: context.RuntimeContext

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.context = context.RuntimeContext()

        logger.info(f"settings.cloud_service_url: {settings.cloud_service_url}")

        # Set the debug port in context so PluginManager can use it
        self.context.ws_debug_port = self.args.ws_debug_port

        self.context.plugin_mgr = plugin_mgr_cls.PluginManager(self.context)

        if args.stdio_control:
            self._control_connection_mode = ControlConnectionMode.STDIO
        else:
            self._control_connection_mode = ControlConnectionMode.WS

        # build controllers layer
        if self._control_connection_mode == ControlConnectionMode.STDIO:
            self.context.stdio_server = stdio_controller_server.StdioServerController()

        elif self._control_connection_mode == ControlConnectionMode.WS:
            self.context.ws_control_server = (
                ws_controller_server.WebSocketServerController(
                    self.args.ws_control_port
                )
            )

        # enable debugging ws server
        self.context.ws_debug_server = ws_controller_server.WebSocketServerController(
            self.args.ws_debug_port
        )

    def set_control_handler(
        self, handler: control_handler_cls.ControlConnectionHandler
    ):
        self.context.control_handler = handler
        task = asyncio.create_task(handler.run())
        logger.info("Got control connection.")
        if self.context.plugin_mgr.wait_for_control_connection is not None:
            self.context.plugin_mgr.wait_for_control_connection.set_result(None)
            # mark as done, indicates all installed plugins are already launched
            # so next time then langbot reconnects, all plugins will not be launched again
            self.context.plugin_mgr.wait_for_control_connection = None
        return task

    async def run(self):
        tasks = []

        # ==== control server ====
        async def new_control_connection_callback(connection: Connection):
            handler = control_handler_cls.ControlConnectionHandler(
                connection, self.context
            )
            await self.set_control_handler(handler)

        if self.context.stdio_server:
            tasks.append(self.context.stdio_server.run(new_control_connection_callback))

        if self.context.ws_control_server:
            tasks.append(
                self.context.ws_control_server.run(new_control_connection_callback)
            )

        # ==== plugin debug server ====
        async def new_plugin_debug_connection_callback(connection: Connection):
            plugin_handler = plugin_handler_cls.PluginConnectionHandler(
                connection, self.context, debug_plugin=True
            )

            await self.context.plugin_mgr.add_plugin_handler(plugin_handler)

        if self.context.ws_debug_server:
            tasks.append(
                self.context.ws_debug_server.run(new_plugin_debug_connection_callback)
            )

        # ==== check and install dependencies for all plugins ====
        if not self.args.skip_deps_check:
            logger.info("Ensuring all installed plugins dependencies are installed...")
            await self.context.plugin_mgr.ensure_all_plugins_dependencies_installed()

        # ==== launch plugin processes ====
        if not self.args.debug_only:
            tasks.append(self.context.plugin_mgr.launch_all_plugins())

        await asyncio.gather(*tasks)

    async def shutdown(self):
        await self.context.plugin_mgr.shutdown_all_plugins()


def main(args: argparse.Namespace):
    # Configure logging for runtime
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s.%(msecs)03d] %(filename)s (%(lineno)d) - [%(levelname)s] : %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    app = RuntimeApplication(args)

    try:
        asyncio.run(app.run())
    except asyncio.CancelledError:
        logger.info("Runtime application cancelled")
        return
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, exiting...")
        return
