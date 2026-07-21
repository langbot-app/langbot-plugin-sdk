from __future__ import annotations

import asyncio
import json
import logging

from langbot_plugin.runtime.io import connection
from langbot_plugin.runtime.io.connection import MAX_MESSAGE_BYTES, split_utf8_chunks
from langbot_plugin.entities.io.errors import ConnectionClosedError

logger = logging.getLogger(__name__)


class StdioConnection(connection.Connection):
    """The connection for Stdio connections."""

    process: asyncio.subprocess.Process | None = None

    def __init__(
        self,
        stdout: asyncio.StreamReader,
        stdin: asyncio.StreamWriter,
        process: asyncio.subprocess.Process | None = None,
        chunk_size: int = 16 * 1024,  # 16KB chunks by default
    ):
        self.stdout = stdout
        self.stdin = stdin
        self.process = process
        self.chunk_size = chunk_size
        self._send_lock = asyncio.Lock()  # 发送锁，防止并发发送冲突

        self._process_exit_task = None

    async def send(self, message: str) -> None:
        """Send message with chunking support for large data."""
        async with self._send_lock:  # 确保同一时间只有一个send操作
            message_bytes = message.encode("utf-8")
            message_size = len(message_bytes)
            if message_size > MAX_MESSAGE_BYTES:
                raise ValueError(
                    f"Runtime message exceeds {MAX_MESSAGE_BYTES} byte limit"
                )

            # For small messages, send directly
            if message_size <= self.chunk_size:
                try:
                    self.stdin.write(message_bytes + b"\n")
                    await self.stdin.drain()
                except Exception:
                    raise ConnectionClosedError("Connection closed during send")
                return

            # For large messages, send in chunks
            try:
                # Send start marker for chunked message
                chunk_header = json.dumps(
                    {"type": "chunk_start", "total_size": message_size}
                )
                self.stdin.write(chunk_header.encode("utf-8") + b"\n")
                await self.stdin.drain()

                # Send message in chunks
                offset = 0
                for chunk_text in split_utf8_chunks(message, self.chunk_size):
                    chunk_size = len(chunk_text.encode("utf-8"))
                    chunk_msg = json.dumps(
                        {
                            "type": "chunk_data",
                            "data": chunk_text,
                            "offset": offset,
                        }
                    )
                    self.stdin.write(chunk_msg.encode("utf-8") + b"\n")
                    await self.stdin.drain()
                    offset += chunk_size
                    # Small delay to prevent overwhelming the connection
                    await asyncio.sleep(0.001)

                # Send end marker
                chunk_end = json.dumps({"type": "chunk_end"})
                self.stdin.write(chunk_end.encode("utf-8") + b"\n")
                await self.stdin.drain()

            except Exception:
                raise ConnectionClosedError("Connection closed during send")

    def _is_valid_json(self, message: str) -> bool:
        """Check if message is valid JSON."""
        try:
            json.loads(message)
            return True
        except json.JSONDecodeError:
            return False

    async def _read_single_line(self) -> str:
        """Read a single line with process monitoring."""
        if self.process is not None and self._process_exit_task is None:
            self._process_exit_task = asyncio.create_task(self.process.wait())

        read_task = asyncio.create_task(self.stdout.readline())
        tasks = [read_task]
        if self._process_exit_task is not None:
            tasks.append(self._process_exit_task)

        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        if self._process_exit_task is not None and self._process_exit_task in done:
            raise ConnectionClosedError("Connection closed")

        if read_task in done:
            s_bytes = read_task.result()
            if not s_bytes:
                # EOF received - connection is closed
                if self._process_exit_task is not None:
                    if self._process_exit_task.done():
                        await self._process_exit_task
                        raise ConnectionClosedError("标准输出流已关闭，子进程已退出。")
                    else:
                        raise ConnectionClosedError("标准输出流意外关闭。")
                else:
                    # process is None but still received EOF - connection is closed
                    raise ConnectionClosedError("标准输出流已关闭。")
            return s_bytes.decode().strip()

        raise ConnectionClosedError("Unexpected error in reading")

    async def receive(self) -> str:
        """Receive message with chunked message support."""
        try:
            while True:
                line = await self._read_single_line()

                if not line:
                    continue

                # Try to parse as JSON to check for chunked messages
                if line.startswith("{") and line.endswith("}"):
                    if self._is_valid_json(line):
                        try:
                            msg_data = json.loads(line)

                            # Handle chunked messages
                            if isinstance(msg_data, dict) and "type" in msg_data:
                                if msg_data["type"] == "chunk_start":
                                    # Start receiving chunked message
                                    chunks = []
                                    total_size = int(msg_data.get("total_size", -1))
                                    if not 0 <= total_size <= MAX_MESSAGE_BYTES:
                                        raise ConnectionClosedError(
                                            "Invalid runtime chunked message size"
                                        )
                                    received_size = 0

                                    while True:
                                        chunk_line = await self._read_single_line()
                                        if not chunk_line or not self._is_valid_json(
                                            chunk_line
                                        ):
                                            continue

                                        chunk_data = json.loads(chunk_line)
                                        if chunk_data.get("type") == "chunk_data":
                                            chunk_text = chunk_data.get("data", "")
                                            if (
                                                chunk_data.get("offset")
                                                != received_size
                                            ):
                                                raise ConnectionClosedError(
                                                    "Invalid runtime chunk offset"
                                                )
                                            received_size += len(
                                                chunk_text.encode("utf-8")
                                            )
                                            if received_size > total_size:
                                                raise ConnectionClosedError(
                                                    "Runtime chunked message exceeds declared size"
                                                )
                                            chunks.append(chunk_text)
                                        elif chunk_data.get("type") == "chunk_end":
                                            if received_size != total_size:
                                                raise ConnectionClosedError(
                                                    "Incomplete runtime chunked message"
                                                )
                                            # Reconstruct original message
                                            return "".join(chunks)

                                        # Yield control periodically
                                        if len(chunks) % 50 == 0:
                                            await asyncio.sleep(0)

                                # Regular message (not chunk related)
                                elif msg_data["type"] not in [
                                    "chunk_start",
                                    "chunk_data",
                                    "chunk_end",
                                ]:
                                    return line
                            else:
                                # Regular JSON message
                                return line
                        except (json.JSONDecodeError, KeyError):
                            # If JSON parsing fails, treat as regular message
                            return line
                    else:
                        # Not valid JSON, but looks like JSON format
                        return line

        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            raise ConnectionClosedError("Connection closed")

    async def close(self) -> None:
        self.stdin.close()
