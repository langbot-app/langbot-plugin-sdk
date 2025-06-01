from __future__ import annotations

import asyncio
import websockets

from langbot_plugin.runtime.io.connections import ws as ws_connection
from langbot_plugin.runtime.io.handlers import control as control_handler
from langbot_plugin.runtime.io import handler as io_handler


class ControlConnectionWebSocketServer:
    """The server for control connection WebSocket connections."""

    def __init__(self, port: int, handler_manager: io_handler.HandlerManager):
        self.port = port
        self.handler_manager = handler_manager

    async def run(self):
        server = await websockets.serve(self.handle_connection, "0.0.0.0", self.port)
        await server.wait_closed()

    async def handle_connection(self, websocket: websockets.ServerConnection):
        print(f"New control connection from {websocket.remote_address}")
        connection = ws_connection.WebSocketConnection(websocket)
        handler = control_handler.ControlConnectionHandler(connection)
        task = self.handler_manager.set_control_handler(handler)
        await task


class DebugConnectionWebSocketServer:
    """The server for debug connection WebSocket connections."""

    def __init__(self, port: int, handler_manager: io_handler.HandlerManager):
        self.port = port
        self.handler_manager = handler_manager

    async def run(self):
        server = await websockets.serve(self.handle_connection, "0.0.0.0", self.port)
        await server.wait_closed()

    async def handle_connection(self, websocket: websockets.ServerConnection):
        print(f"New connection from {websocket.remote_address}")
        await websocket.send("Hello, world!")
        await websocket.close()


class WebSocketServer:
    """The server for control connection WebSocket connections."""

    def __init__(
        self,
        control_port: int,
        debug_port: int,
        handler_manager: io_handler.HandlerManager,
    ):
        self.control_port = control_port
        self.debug_port = debug_port
        self.handler_manager = handler_manager

    async def run(self):
        print(
            f"Starting WebSocket server on port {self.control_port} for control connections"
        )
        print(
            f"Starting WebSocket server on port {self.debug_port} for debug connections"
        )
        control_server = ControlConnectionWebSocketServer(
            self.control_port, self.handler_manager
        )
        debug_server = DebugConnectionWebSocketServer(
            self.debug_port, self.handler_manager
        )

        await asyncio.gather(control_server.run(), debug_server.run())
