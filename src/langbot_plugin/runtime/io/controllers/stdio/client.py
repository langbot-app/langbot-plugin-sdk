from __future__ import annotations

from typing import Callable, Coroutine, Any
import asyncio

from langbot_plugin.runtime.io.connections import stdio as stdio_connection
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.controller import Controller


class StdioClientController(Controller):
    """The controller for stdio client."""

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str],
    ):
        self.command = command
        self.args = args
        self.env = env

    async def run(
        self,
        new_connection_callback: Callable[[Connection], Coroutine[Any, Any, None]],
    ):
        proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            env=self.env,
        )

        if proc.stdout is None or proc.stdin is None:
            raise RuntimeError("Failed to create subprocess pipes")

        connection = stdio_connection.StdioConnection(proc.stdout, proc.stdin)
        await new_connection_callback(connection)
