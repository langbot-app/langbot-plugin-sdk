from __future__ import annotations

import websockets
import asyncio
import json

from langbot_plugin.runtime.io import connection as io_connection
from langbot_plugin.entities.io.errors import ConnectionClosedError


class WebSocketConnection(io_connection.Connection):
    """The connection for WebSocket connections."""

    def __init__(
        self, websocket: websockets.ServerConnection | websockets.ClientConnection,
        chunk_size: int = 64 * 1024  # 64KB chunks by default
    ):
        self.websocket = websocket
        self.chunk_size = chunk_size
        self._send_lock = asyncio.Lock()  # 发送锁，防止并发发送冲突

    async def send(self, message: str) -> None:
        """Send message with chunking support for large data."""
        async with self._send_lock:  # 确保同一时间只有一个send操作
            message_bytes = message.encode('utf-8')
            message_size = len(message_bytes)

            # For small messages, send directly
            if message_size <= self.chunk_size:
                try:
                    await self.websocket.send(message, text=True)
                except websockets.exceptions.ConnectionClosed:
                    raise ConnectionClosedError("Connection closed during send")
                return

            # For large messages, use chunking with streaming
            try:
                # Send message in chunks to avoid timeout
                for i in range(0, message_size, self.chunk_size):
                    chunk = message_bytes[i:i + self.chunk_size].decode('utf-8')
                    await self.websocket.send(chunk, text=True)
                    # Small delay to prevent overwhelming the connection
                    await asyncio.sleep(0.001)
            except websockets.exceptions.ConnectionClosed:
                raise ConnectionClosedError("Connection closed during send")

    def _is_valid_json(self, message: str) -> bool:
        try:
            json.loads(message)
            return True
        except json.JSONDecodeError:
            return False

    async def receive(self) -> str:
        """Receive message with streaming support and timeout protection."""
        try:
            # Use recv_streaming for better handling of large messages
            whole_message = ""
            message_chunks = []

            while True:

                async for data in self.websocket.recv_streaming(decode=True):
                    message_chunks.append(data)
                    # Yield control periodically to prevent blocking
                    if len(message_chunks) % 100 == 0:
                        await asyncio.sleep(0)

                # Join all chunks efficiently
                whole_message = "".join(message_chunks)

                if self._is_valid_json(whole_message):
                    return whole_message
                else:
                    await asyncio.sleep(0.001)

        except websockets.exceptions.ConnectionClosed:
            raise ConnectionClosedError("Connection closed")

    async def close(self) -> None:
        await self.websocket.close()
