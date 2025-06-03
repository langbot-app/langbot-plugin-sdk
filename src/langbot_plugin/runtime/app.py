from __future__ import annotations

import argparse
from enum import Enum

import asyncio

from langbot_plugin.runtime.io.controllers.stdio import (
    server as stdio_controller_server,
)
from langbot_plugin.runtime.io.controllers.ws import server as ws_controller_server
from langbot_plugin.runtime.io import handler as io_handler
from langbot_plugin.runtime.io.handlers import control as control_handler
from langbot_plugin.runtime.io.connection import Connection


class ControlConnectionMode(Enum):
    STDIO = "stdio"
    WS = "ws"


class Application:
    """Runtime application context."""

    handler_manager: io_handler.RuntimeHandlerManager  # communication handler manager

    _control_connection_mode: ControlConnectionMode

    stdio_server: stdio_controller_server.StdioServerController | None = (
        None  # stdio control server
    )
    ws_control_server: ws_controller_server.WebSocketServerController | None = (
        None  # ws control/debug server
    )

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.handler_manager = io_handler.RuntimeHandlerManager()

        if args.stdio_control:
            self._control_connection_mode = ControlConnectionMode.STDIO
        else:
            self._control_connection_mode = ControlConnectionMode.WS

        # build controllers layer
        if self._control_connection_mode == ControlConnectionMode.STDIO:
            self.stdio_server = stdio_controller_server.StdioServerController()

        elif self._control_connection_mode == ControlConnectionMode.WS:
            self.ws_control_server = ws_controller_server.WebSocketServerController(
                self.args.ws_control_port
            )

    async def run(self):
        tasks = []

        async def new_control_connection_callback(connection: Connection):
            handler = control_handler.ControlConnectionHandler(connection)
            task = self.handler_manager.set_control_handler(handler)
            await task

        if self.stdio_server:
            tasks.append(self.stdio_server.run(new_control_connection_callback))

        if self.ws_control_server:
            tasks.append(self.ws_control_server.run(new_control_connection_callback))

        await asyncio.gather(*tasks)


def main(args: argparse.Namespace):
    app = Application(args)
    asyncio.run(app.run())
