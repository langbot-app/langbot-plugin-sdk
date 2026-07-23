from __future__ import annotations

from typing import Callable, Coroutine, Any
import asyncio
import contextlib

from langbot_plugin.runtime.io.connections import stdio as stdio_connection
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.controller import Controller


class StdioClientController(Controller):
    """The controller for stdio client."""

    process: asyncio.subprocess.Process | None = None
    connection: stdio_connection.StdioConnection | None = None

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str],
        working_dir: str = ".",
        *,
        capture_stderr: bool = False,
    ):
        self.command = command
        self.args = args
        self.env = env
        self.working_dir = working_dir
        self.capture_stderr = capture_stderr

    async def run(
        self,
        new_connection_callback: Callable[[Connection], Coroutine[Any, Any, None]],
    ):
        self.process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE if self.capture_stderr else None,
            env=self.env,
            cwd=self.working_dir,
        )

        if self.process.stdout is None or self.process.stdin is None:
            raise RuntimeError("Failed to create subprocess pipes")

        self.connection = stdio_connection.StdioConnection(
            self.process.stdout, self.process.stdin, process=self.process
        )
        try:
            await new_connection_callback(self.connection)
        finally:
            await self.close()

    async def close(self) -> None:
        """Close pipes and reap the owned subprocess."""
        if self.connection is not None:
            with contextlib.suppress(Exception):
                await self.connection.close()
            self.connection = None

        process = self.process
        if process is None:
            return
        self.process = None
        if process.returncode is not None:
            return

        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
