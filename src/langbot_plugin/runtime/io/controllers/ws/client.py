from __future__ import annotations

from typing import Callable, Coroutine, Any

import websockets

from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.connections import ws as ws_connection
from langbot_plugin.runtime.io.controller import Controller


class WebSocketClientController(Controller):
    """The controller for WebSocket client."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url

    async def run(
        self,
        new_connection_callback: Callable[[Connection], Coroutine[Any, Any, None]],
    ):
        async with websockets.connect(self.ws_url) as websocket:
            connection = ws_connection.WebSocketConnection(websocket)
            await new_connection_callback(connection)
