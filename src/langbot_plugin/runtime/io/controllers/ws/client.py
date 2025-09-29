from __future__ import annotations

from typing import Callable, Coroutine, Any

import websockets

from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.connections import ws as ws_connection
from langbot_plugin.runtime.io.controller import Controller


class WebSocketClientController(Controller):
    """The controller for WebSocket client."""

    def __init__(
        self,
        ws_url: str,
        make_connection_failed_callback: Callable[
            [Controller, Exception | None], Coroutine[Any, Any, None]
        ],
    ):
        self.ws_url = ws_url
        self.make_connection_failed_callback = make_connection_failed_callback

    async def run(
        self,
        new_connection_callback: Callable[[Connection], Coroutine[Any, Any, None]],
    ):
        try:
            async with websockets.connect(self.ws_url, open_timeout=10) as websocket:
                connection = ws_connection.WebSocketConnection(websocket)
                await new_connection_callback(connection)
        except Exception as e:
            await self.make_connection_failed_callback(self, e)
