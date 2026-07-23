from __future__ import annotations

from http import HTTPStatus
import websockets
from typing import Callable, Coroutine, Any
import logging

from langbot_plugin.runtime.io.connections import ws as ws_connection
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.controller import Controller
from langbot_plugin.runtime.io.connection import MAX_MESSAGE_BYTES

logger = logging.getLogger(__name__)
protocol_logger = logging.getLogger(f"{__name__}.protocol")
protocol_logger.setLevel(logging.WARNING)


def process_http_request(connection, request):
    """Serve a quiet HTTP health endpoint alongside the WebSocket endpoint."""
    if request.path == "/healthz":
        return connection.respond(HTTPStatus.OK, "ok\n")
    return None


class WebSocketServerController(Controller):
    """The controller for WebSocket server."""

    _new_connection_callback: Callable[[Connection], Coroutine[Any, Any, None]]

    def __init__(self, port: int):
        self.port = port

    async def run(
        self,
        new_connection_callback: Callable[[Connection], Coroutine[Any, Any, None]],
    ):
        self._new_connection_callback = new_connection_callback

        server = await websockets.serve(
            self.handle_connection,
            "0.0.0.0",
            self.port,
            max_size=MAX_MESSAGE_BYTES,
            process_request=process_http_request,
            logger=protocol_logger,
        )
        logger.info(f"WebSocket server started on port {self.port}")
        try:
            await server.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def handle_connection(self, websocket: websockets.ServerConnection):
        logger.info(f"New connection from {websocket.remote_address}")
        connection = ws_connection.WebSocketConnection(websocket)
        await self._new_connection_callback(connection)
