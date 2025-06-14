# Stdio server for LangBot control connection
from __future__ import annotations

from typing import Callable, Coroutine, Any
import asyncio
import sys

from langbot_plugin.runtime.io.connections import stdio as stdio_connection
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.controller import Controller

_DEFAULT_LIMIT = 64 * 1024


async def connect_stdin_stdout(limit=_DEFAULT_LIMIT, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader(limit=limit, loop=loop)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    dummy = asyncio.Protocol()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)  # sets read_transport
    w_transport, _ = await loop.connect_write_pipe(lambda: dummy, sys.stdout)
    writer = asyncio.StreamWriter(w_transport, protocol, reader, loop)
    return reader, writer


class StdioServerController(Controller):
    async def run(
        self,
        new_connection_callback: (Callable[[Connection], Coroutine[Any, Any, None]]),
    ):
        stdin_reader, stdout_writer = await connect_stdin_stdout()

        # 创建连接
        connection = stdio_connection.StdioConnection(stdin_reader, stdout_writer)

        # 调用回调函数处理新连接
        await new_connection_callback(connection)
