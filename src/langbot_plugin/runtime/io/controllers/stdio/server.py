# Stdio server for LangBot control connection
from __future__ import annotations

from typing import Callable, Coroutine, Any

from langbot_plugin.runtime.io.connections import stdio as stdio_connection
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.controller import Controller


class StdioServerController(Controller):
    async def run(
        self,
        new_connection_callback: (Callable[[Connection], Coroutine[Any, Any, None]]),
    ):
        connection = stdio_connection.StdioConnection()
        await new_connection_callback(connection)
