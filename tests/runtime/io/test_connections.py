from __future__ import annotations

import json

from langbot_plugin.runtime.io.connections.stdio import StdioConnection
from langbot_plugin.runtime.io.connections.ws import WebSocketConnection


class FakeStreamReader:
    def __init__(self, lines: list[bytes]):
        self.lines = lines

    async def readline(self):
        return self.lines.pop(0)


class FakeStreamWriter:
    def __init__(self):
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes):
        self.writes.append(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True


class AsyncChunkIterator:
    def __init__(self, chunks: list[str]):
        self.chunks = chunks

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)


class FakeWebSocket:
    def __init__(self, receive_batches: list[list[str]] | None = None):
        self.sent: list[tuple[str, bool]] = []
        self.receive_batches = receive_batches or []
        self.closed = False

    async def send(self, data: str, text: bool = False):
        self.sent.append((data, text))

    def recv_streaming(self, decode: bool = False):
        return AsyncChunkIterator(self.receive_batches.pop(0))

    async def close(self):
        self.closed = True


async def test_stdio_connection_sends_small_message_with_newline():
    writer = FakeStreamWriter()
    connection = StdioConnection(FakeStreamReader([]), writer)

    await connection.send('{"ok": true}')

    assert writer.writes == [b'{"ok": true}\n']


async def test_stdio_connection_sends_large_message_as_json_chunks():
    writer = FakeStreamWriter()
    connection = StdioConnection(FakeStreamReader([]), writer, chunk_size=4)

    await connection.send("abcdefghi")

    payloads = [json.loads(line.decode()) for line in writer.writes]
    assert payloads[0] == {"type": "chunk_start", "total_size": 9}
    assert payloads[1:4] == [
        {"type": "chunk_data", "data": "abcd", "offset": 0},
        {"type": "chunk_data", "data": "efgh", "offset": 4},
        {"type": "chunk_data", "data": "i", "offset": 8},
    ]
    assert payloads[4] == {"type": "chunk_end"}


async def test_stdio_connection_receives_json_message_after_blank_line():
    reader = FakeStreamReader([b"\n", b'{"type": "event", "id": 1}\n'])
    connection = StdioConnection(reader, FakeStreamWriter())

    assert await connection.receive() == '{"type": "event", "id": 1}'


async def test_stdio_connection_reassembles_chunked_message():
    chunk_lines = [
        {"type": "chunk_start", "total_size": 11},
        {"type": "chunk_data", "data": "hello ", "offset": 0},
        {"type": "chunk_data", "data": "world", "offset": 6},
        {"type": "chunk_end"},
    ]
    reader = FakeStreamReader(
        [json.dumps(chunk).encode() + b"\n" for chunk in chunk_lines]
    )
    connection = StdioConnection(reader, FakeStreamWriter())

    assert await connection.receive() == "hello world"


async def test_stdio_connection_close_closes_writer():
    writer = FakeStreamWriter()
    connection = StdioConnection(FakeStreamReader([]), writer)

    await connection.close()

    assert writer.closed is True


async def test_websocket_connection_sends_small_message_directly():
    websocket = FakeWebSocket()
    connection = WebSocketConnection(websocket)

    await connection.send('{"ok": true}')

    assert websocket.sent == [('{"ok": true}', True)]


async def test_websocket_connection_sends_large_message_in_chunks():
    websocket = FakeWebSocket()
    connection = WebSocketConnection(websocket, chunk_size=4)

    await connection.send("abcdefghi")

    assert websocket.sent == [("abcd", True), ("efgh", True), ("i", True)]


async def test_websocket_connection_receives_streamed_json_message():
    websocket = FakeWebSocket(receive_batches=[['{"ok": ', "true}"]])
    connection = WebSocketConnection(websocket)

    assert await connection.receive() == '{"ok": true}'


async def test_websocket_connection_close_closes_socket():
    websocket = FakeWebSocket()
    connection = WebSocketConnection(websocket)

    await connection.close()

    assert websocket.closed is True
