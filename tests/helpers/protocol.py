from __future__ import annotations

import asyncio
import json
from typing import Any

from langbot_plugin.entities.io.errors import ConnectionClosedError
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.handler import Handler


class ProtocolConnection(Connection):
    def __init__(self):
        self.incoming: asyncio.Queue[str | BaseException] = asyncio.Queue()
        self.sent: list[str] = []
        self.sent_event = asyncio.Event()
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)
        self.sent_event.set()

    async def receive(self) -> str:
        message = await self.incoming.get()
        if isinstance(message, BaseException):
            raise message
        return message

    async def close(self) -> None:
        self.closed = True

    async def send_peer_request(
        self,
        action: str,
        data: dict[str, Any] | None = None,
        seq_id: int = 1,
    ) -> None:
        await self.incoming.put(
            json.dumps({"seq_id": seq_id, "action": action, "data": data or {}})
        )

    async def send_peer_response(
        self,
        seq_id: int,
        code: int = 0,
        message: str = "success",
        data: dict[str, Any] | None = None,
        chunk_status: str = "continue",
    ) -> None:
        await self.incoming.put(
            json.dumps(
                {
                    "seq_id": seq_id,
                    "code": code,
                    "message": message,
                    "data": data or {},
                    "chunk_status": chunk_status,
                }
            )
        )

    async def close_peer(self) -> None:
        await self.incoming.put(ConnectionClosedError("closed"))

    async def sent_messages(self, count: int = 1) -> list[dict[str, Any]]:
        for _ in range(50):
            if len(self.sent) >= count:
                return [json.loads(message) for message in self.sent[:count]]
            await asyncio.sleep(0.01)
        raise AssertionError(f"timed out waiting for {count} sent messages")


class ProtocolSession:
    def __init__(self, handler: Handler):
        self.handler = handler
        self.connection = handler.conn
        assert isinstance(self.connection, ProtocolConnection)
        self._task: asyncio.Task | None = None

    async def __aenter__(self):
        self._task = asyncio.create_task(self.handler.run())
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.connection.close_peer()
        if self._task is not None:
            await self._task
        return False

    async def request(
        self,
        action: str,
        data: dict[str, Any] | None = None,
        seq_id: int = 1,
    ) -> dict[str, Any]:
        start = len(self.connection.sent)
        await self.connection.send_peer_request(action, data, seq_id)
        for _ in range(50):
            if len(self.connection.sent) > start:
                return json.loads(self.connection.sent[-1])
            await asyncio.sleep(0.01)
        raise AssertionError(f"timed out waiting for response to {action}")

    async def request_messages(
        self,
        action: str,
        data: dict[str, Any] | None = None,
        seq_id: int = 1,
        count: int = 1,
    ) -> list[dict[str, Any]]:
        start = len(self.connection.sent)
        await self.connection.send_peer_request(action, data, seq_id)
        for _ in range(50):
            if len(self.connection.sent) >= start + count:
                return [
                    json.loads(message)
                    for message in self.connection.sent[start : start + count]
                ]
            await asyncio.sleep(0.01)
        raise AssertionError(f"timed out waiting for {count} responses to {action}")
