from __future__ import annotations

import asyncio

from langbot_plugin.runtime.io import connection


class StdioConnection(connection.Connection):
    """The connection for Stdio connections."""

    def __init__(self, stdout: asyncio.StreamReader, stdin: asyncio.StreamWriter):
        self.stdout = stdout
        self.stdin = stdin

    async def send(self, message: str) -> None:
        self.stdin.write(message.encode() + b"\n")
        await self.stdin.drain()

    async def receive(self) -> str:
        while True:
            s_bytes = await self.stdout.readline()
            s = s_bytes.decode().strip()
            if s.startswith("{") and s.endswith("}"):
                return s

    async def close(self) -> None:
        pass
