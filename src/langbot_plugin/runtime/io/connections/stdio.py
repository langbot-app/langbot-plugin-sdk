from __future__ import annotations

import asyncio

from langbot_plugin.runtime.io import connection


class StdioConnection(connection.Connection):
    """The connection for Stdio connections."""

    def __init__(self):
        pass

    async def send(self, message: str) -> None:
        print(message)

    async def receive(self) -> str:
        while True:
            s = await asyncio.to_thread(input)
            if s.startswith("{") and s.endswith("}"):
                return s

    async def close(self) -> None:
        pass
