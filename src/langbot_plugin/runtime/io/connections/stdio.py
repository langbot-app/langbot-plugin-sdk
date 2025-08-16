from __future__ import annotations

import asyncio

from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.errors import ConnectionClosedError


class StdioConnection(connection.Connection):
    """The connection for Stdio connections."""

    process: asyncio.subprocess.Process | None = None

    def __init__(self, stdout: asyncio.StreamReader, stdin: asyncio.StreamWriter, process: asyncio.subprocess.Process | None = None):
        self.stdout = stdout
        self.stdin = stdin
        self.process = process

        self._process_exit_task = None

    async def send(self, message: str) -> None:
        self.stdin.write(message.encode() + b"\n")
        await self.stdin.drain()

    async def receive(self) -> str:

        if self.process is not None and self._process_exit_task is None:
            self._process_exit_task = asyncio.create_task(self.process.wait())

        try:
            while True:

                read_task = asyncio.create_task(self.stdout.readline())

                tasks = [read_task]
                if self._process_exit_task is not None:
                    tasks.append(self._process_exit_task)

                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                
                if self._process_exit_task is not None and self._process_exit_task in done:
                    raise ConnectionClosedError("Connection closed")
                
                if read_task in done:
                    s_bytes = read_task.result()
                    
                    # 如果 readline 返回空字节串，说明流已关闭
                    if not s_bytes:
                        # 再次检查进程是否已退出，以获得更准确的错误信息
                        if self._process_exit_task is not None:
                            if self._process_exit_task.done():
                                await self._process_exit_task
                                raise ConnectionClosedError("标准输出流已关闭，子进程已退出。")
                            else:
                                raise ConnectionClosedError("标准输出流意外关闭。")
                    
                    s = s_bytes.decode().strip()
                    if s.startswith("{") and s.endswith("}"):
                        return s
        except Exception as e:
            print(f"Error receiving message: {e}")
            raise ConnectionClosedError("Connection closed")

    async def close(self) -> None:
        self.stdin.close()
