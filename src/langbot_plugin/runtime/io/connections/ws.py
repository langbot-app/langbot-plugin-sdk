from __future__ import annotations

import websockets

from langbot_plugin.runtime.io import connection as io_connection
from langbot_plugin.entities.io.errors import ConnectionClosedError


class WebSocketConnection(io_connection.Connection):
    """The connection for WebSocket connections."""

    def __init__(
        self, websocket: websockets.ServerConnection | websockets.ClientConnection
    ):
        self.websocket = websocket

    async def send(self, message: str) -> None:
        await self.websocket.send(message, text=True)

    async def receive(self) -> str:
        try:
            # data = await self.websocket.recv(decode=True)
            # return data
            
            # switch to use recv_streaming
            whole_message = ""
            async for data in self.websocket.recv_streaming(decode=True):
                whole_message += data
            return whole_message
        except websockets.exceptions.ConnectionClosed:
            raise ConnectionClosedError("Connection closed")

    async def close(self) -> None:
        await self.websocket.close()
