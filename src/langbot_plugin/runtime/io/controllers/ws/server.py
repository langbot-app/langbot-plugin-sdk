from __future__ import annotations

import hmac
import inspect
from http import HTTPStatus
import websockets
from collections.abc import Awaitable, Mapping
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
    if getattr(request, "path", None) == "/healthz":
        return connection.respond(HTTPStatus.OK, "ok\n")
    return None


class WebSocketServerController(Controller):
    """The controller for WebSocket server."""

    _new_connection_callback: Callable[[Connection], Coroutine[Any, Any, None]]

    def __init__(
        self,
        port: int,
        *,
        host: str = "0.0.0.0",
        expected_headers: dict[str, str] | None = None,
        request_authenticator: (
            Callable[[Mapping[str, str]], bool | Awaitable[bool]] | None
        ) = None,
    ):
        self.port = port
        self.host = host
        self.expected_headers = dict(expected_headers or {})
        self.request_authenticator = request_authenticator

    async def run(
        self,
        new_connection_callback: Callable[[Connection], Coroutine[Any, Any, None]],
    ):
        self._new_connection_callback = new_connection_callback

        async def authenticate_request(connection, request):
            health_response = process_http_request(connection, request)
            if health_response is not None:
                return health_response
            for header, expected_value in self.expected_headers.items():
                supplied_value = request.headers.get(header, "")
                if not supplied_value or not hmac.compare_digest(
                    str(expected_value), str(supplied_value)
                ):
                    return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized")
            if self.request_authenticator is not None:
                authenticated = self.request_authenticator(request.headers)
                if inspect.isawaitable(authenticated):
                    authenticated = await authenticated
                if not authenticated:
                    return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized")
            return None

        server = await websockets.serve(
            self.handle_connection,
            self.host,
            self.port,
            max_size=MAX_MESSAGE_BYTES,
            process_request=authenticate_request,
            logger=protocol_logger,
        )
        logger.info(f"WebSocket server started on {self.host}:{self.port}")
        try:
            await server.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    async def handle_connection(self, websocket: websockets.ServerConnection):
        logger.info(f"New connection from {websocket.remote_address}")
        connection = ws_connection.WebSocketConnection(websocket)
        await self._new_connection_callback(connection)
