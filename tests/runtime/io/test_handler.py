from __future__ import annotations

import asyncio
import json

import pytest

from langbot_plugin.entities.io.actions.enums import ActionType, CommonAction
from langbot_plugin.entities.io.errors import (
    ActionCallError,
    ActionCallTimeoutError,
    ConnectionClosedError,
)
from langbot_plugin.entities.io.resp import ActionResponse, ChunkStatus
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.handler import Handler


class SampleAction(ActionType):
    ECHO = "echo"
    STREAM = "stream"


class QueueConnection(Connection):
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


async def _wait_for_sent(conn: QueueConnection, count: int = 1) -> list[dict]:
    for _ in range(50):
        if len(conn.sent) >= count:
            return [json.loads(message) for message in conn.sent]
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {count} sent messages")


@pytest.mark.asyncio
async def test_call_action_sends_request_and_returns_response_data():
    conn = QueueConnection()
    handler = Handler(conn)

    task = asyncio.create_task(
        handler.call_action(SampleAction.ECHO, {"message": "hello"}, timeout=1)
    )
    [request] = await _wait_for_sent(conn)
    assert request["action"] == "echo"
    assert request["data"] == {"message": "hello"}

    handler.resp_waiters[request["seq_id"]].set_result(
        ActionResponse(
            seq_id=request["seq_id"], code=0, message="ok", data={"ok": True}
        )
    )

    assert await task == {"ok": True}
    assert request["seq_id"] not in handler.resp_waiters


@pytest.mark.asyncio
async def test_call_action_timeout_cleans_waiter():
    conn = QueueConnection()
    handler = Handler(conn)

    with pytest.raises(ActionCallTimeoutError, match="Action echo call timed out"):
        await handler.call_action(SampleAction.ECHO, {}, timeout=0.01)

    assert handler.resp_waiters == {}


@pytest.mark.asyncio
async def test_call_action_error_response_should_preserve_peer_message():
    conn = QueueConnection()
    handler = Handler(conn)
    task = asyncio.create_task(handler.call_action(SampleAction.ECHO, {}, timeout=1))
    [request] = await _wait_for_sent(conn)

    handler.resp_waiters[request["seq_id"]].set_result(
        ActionResponse(seq_id=request["seq_id"], code=1, message="peer failed", data={})
    )

    with pytest.raises(ActionCallError, match="^peer failed$"):
        await task


@pytest.mark.asyncio
async def test_call_action_generator_yields_chunks_until_end():
    conn = QueueConnection()
    handler = Handler(conn)
    chunks: list[dict] = []

    async def consume():
        async for chunk in handler.call_action_generator(
            SampleAction.STREAM, {}, timeout=1
        ):
            chunks.append(chunk)

    task = asyncio.create_task(consume())
    [request] = await _wait_for_sent(conn)
    queue = handler.resp_queues[request["seq_id"]]
    await queue.put(
        ActionResponse(
            seq_id=request["seq_id"],
            code=0,
            message="ok",
            data={"part": 1},
            chunk_status=ChunkStatus.CONTINUE,
        )
    )
    await queue.put(
        ActionResponse(
            seq_id=request["seq_id"],
            code=0,
            message="ok",
            data={},
            chunk_status=ChunkStatus.END,
        )
    )

    await task
    assert chunks == [{"part": 1}]
    assert handler.resp_queues == {}


@pytest.mark.asyncio
async def test_run_dispatches_registered_action_and_sends_response():
    conn = QueueConnection()
    handler = Handler(conn)

    @handler.action(SampleAction.ECHO)
    async def echo(data):
        return ActionResponse.success({"echo": data["message"]})

    task = asyncio.create_task(handler.run())
    await conn.incoming.put(
        json.dumps({"seq_id": 7, "action": "echo", "data": {"message": "hi"}})
    )
    [response] = await _wait_for_sent(conn)
    await conn.incoming.put(ConnectionClosedError("closed"))
    await task

    assert response["seq_id"] == 7
    assert response["code"] == 0
    assert response["data"] == {"echo": "hi"}


@pytest.mark.asyncio
async def test_run_sends_error_response_for_unknown_action():
    conn = QueueConnection()
    handler = Handler(conn)

    task = asyncio.create_task(handler.run())
    await conn.incoming.put(json.dumps({"seq_id": 9, "action": "missing", "data": {}}))
    [response] = await _wait_for_sent(conn)
    await conn.incoming.put(ConnectionClosedError("closed"))
    await task

    assert response["seq_id"] == 9
    assert response["code"] == 1
    assert "Action missing not found" in response["message"]


@pytest.mark.asyncio
async def test_run_handles_streaming_action_response():
    conn = QueueConnection()
    handler = Handler(conn)

    @handler.action(SampleAction.STREAM)
    async def stream(_data):
        yield ActionResponse.success({"part": 1})
        yield ActionResponse.success({"part": 2})

    task = asyncio.create_task(handler.run())
    await conn.incoming.put(json.dumps({"seq_id": 3, "action": "stream", "data": {}}))
    responses = await _wait_for_sent(conn, count=3)
    await conn.incoming.put(ConnectionClosedError("closed"))
    await task

    assert [response["chunk_status"] for response in responses] == [
        "continue",
        "continue",
        "end",
    ]
    assert [response["data"] for response in responses] == [
        {"part": 1},
        {"part": 2},
        {},
    ]


@pytest.mark.asyncio
async def test_send_file_calls_file_chunk_action_for_each_chunk(monkeypatch):
    conn = QueueConnection()
    handler = Handler(conn)
    calls: list[dict] = []

    async def fake_call_action(action, data, timeout=15.0):
        calls.append({"action": action, "data": data, "timeout": timeout})
        return {}

    monkeypatch.setattr(handler, "call_action", fake_call_action)
    file_key = await handler.send_file(b"abc", "txt")

    assert file_key.endswith(".txt")
    assert calls[0]["action"] is CommonAction.FILE_CHUNK
    assert calls[0]["data"]["file_length"] == 3
    assert calls[0]["data"]["chunk_amount"] == 1


def test_handler_file_storage_dir_is_created_for_instances(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    Handler(QueueConnection())

    assert (tmp_path / "data" / "temp" / "lbp").is_dir()
