from __future__ import annotations

import argparse
from enum import Enum

import asyncio

from langbot_plugin.runtime.controller.stdio import server as stdio_controller_server
from langbot_plugin.runtime.controller.ws import server as ws_controller_server
from langbot_plugin.runtime.io import handler


class ControlConnectionMode(Enum):
    STDIO = "stdio"
    WS = "ws"


class Application:
    """Runtime application context."""

    handler_manager: handler.HandlerManager

    control_connection_mode: ControlConnectionMode

    stdio_server: stdio_controller_server.StdioServer | None = (
        None  # stdio control server
    )
    ws_server: ws_controller_server.WebSocketServer | None = (
        None  # ws control/debug server
    )

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.handler_manager = handler.HandlerManager()

        if args.stdio_control:
            self.control_connection_mode = ControlConnectionMode.STDIO
        else:
            self.control_connection_mode = ControlConnectionMode.WS

        # build controllers layer
        if self.control_connection_mode == ControlConnectionMode.STDIO:
            self.stdio_server = stdio_controller_server.StdioServer(
                self.handler_manager
            )

        self.ws_server = ws_controller_server.WebSocketServer(
            self.args.ws_control_port, self.args.ws_debug_port, self.handler_manager
        )

    async def run(self):
        tasks = []

        if self.stdio_server:
            tasks.append(self.stdio_server.run())

        if self.ws_server:
            tasks.append(self.ws_server.run())

        await asyncio.gather(*tasks)
