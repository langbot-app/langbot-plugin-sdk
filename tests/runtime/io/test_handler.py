from __future__ import annotations

import asyncio
import base64
import contextlib
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

from tests.helpers.protocol import ProtocolConnection


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
        ActionResponse(
            seq_id=request["seq_id"],
            code=1,
            message="peer failed",
            data={"error": {"code": "peer.failed"}},
        )
    )

    with pytest.raises(ActionCallError, match="^peer failed$") as exc_info:
        await task

    assert exc_info.value.data == {"error": {"code": "peer.failed"}}


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
async def test_call_action_generator_cancel_propagates_and_cleans_queue():
    conn = QueueConnection()
    handler = Handler(conn)

    async def consume():
        async for _chunk in handler.call_action_generator(
            SampleAction.STREAM, {}, timeout=1
        ):
            pass

    task = asyncio.create_task(consume())
    [request] = await _wait_for_sent(conn)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert request["seq_id"] not in handler.resp_queues


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
async def test_run_cancels_active_streaming_action_on_disconnect():
    conn = QueueConnection()
    handler = Handler(conn)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    @handler.action(SampleAction.STREAM)
    async def stream(_data):
        started.set()
        try:
            while True:
                await asyncio.sleep(60)
                yield ActionResponse.success({"part": "late"})
        finally:
            cancelled.set()

    task = asyncio.create_task(handler.run())
    await conn.incoming.put(json.dumps({"seq_id": 3, "action": "stream", "data": {}}))
    await asyncio.wait_for(started.wait(), timeout=1)

    await conn.incoming.put(ConnectionClosedError("closed"))
    await task

    assert cancelled.is_set()
    assert handler._active_tasks == set()


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


# ---------------------------------------------------------------------------
# Response routing through the receive loop (run()).
#
# The tests above resolve futures by poking handler.resp_waiters directly,
# which bypasses run(). These drive a real response message in through the
# connection so the full request -> wire -> response -> waiter path is covered.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_routes_response_to_call_action_waiter():
    conn = ProtocolConnection()
    handler = Handler(conn)
    run_task = asyncio.create_task(handler.run())

    call_task = asyncio.create_task(
        handler.call_action(SampleAction.ECHO, {"x": 1}, timeout=1)
    )
    [request] = await conn.sent_messages(1)
    assert request["action"] == "echo"

    await conn.send_peer_response(request["seq_id"], code=0, data={"ok": True})

    assert await call_task == {"ok": True}
    assert handler.resp_waiters == {}

    await conn.close_peer()
    await run_task


@pytest.mark.asyncio
async def test_run_routes_streaming_response_to_generator_queue():
    conn = ProtocolConnection()
    handler = Handler(conn)
    run_task = asyncio.create_task(handler.run())

    chunks: list[dict] = []

    async def consume():
        async for chunk in handler.call_action_generator(
            SampleAction.STREAM, {}, timeout=1
        ):
            chunks.append(chunk)

    consume_task = asyncio.create_task(consume())
    [request] = await conn.sent_messages(1)
    seq_id = request["seq_id"]

    await conn.send_peer_response(seq_id, data={"part": 1}, chunk_status="continue")
    await conn.send_peer_response(seq_id, data={"part": 2}, chunk_status="continue")
    await conn.send_peer_response(seq_id, data={}, chunk_status="end")

    await consume_task
    assert chunks == [{"part": 1}, {"part": 2}]
    assert handler.resp_queues == {}

    await conn.close_peer()
    await run_task


@pytest.mark.asyncio
async def test_run_skips_none_message_and_keeps_running():
    conn = ProtocolConnection()
    handler = Handler(conn)

    @handler.action(SampleAction.ECHO)
    async def echo(data):
        return ActionResponse.success({"seen": data})

    run_task = asyncio.create_task(handler.run())
    await conn.incoming.put(None)  # receive() returns None -> loop should just continue

    await conn.send_peer_request("echo", {"v": 1}, seq_id=5)
    [response] = await conn.sent_messages(1)

    assert response["seq_id"] == 5
    assert response["data"] == {"seen": {"v": 1}}

    await conn.close_peer()
    await run_task


@pytest.mark.asyncio
async def test_run_reconnects_while_disconnect_callback_returns_true():
    conn = ProtocolConnection()
    handler = Handler(conn)

    attempts: list[Handler] = []

    async def on_disconnect(h: Handler) -> bool:
        attempts.append(h)
        return len(attempts) < 2  # reconnect once, then give up

    handler.set_disconnect_callback(on_disconnect)

    run_task = asyncio.create_task(handler.run())
    await conn.incoming.put(ConnectionClosedError("drop-1"))  # -> reconnect (True)
    await conn.incoming.put(ConnectionClosedError("drop-2"))  # -> give up -> break
    await run_task

    assert len(attempts) == 2
    assert attempts[0] is handler


@pytest.mark.asyncio
async def test_run_supports_sync_action_handler_returning_response():
    conn = ProtocolConnection()
    handler = Handler(conn)

    # A handler whose return value is an ActionResponse rather than a coroutine;
    # run() handles this via its `isinstance(response, Coroutine)` guard.
    def sync_echo(data):
        return ActionResponse.success({"echoed": data})

    handler.actions[SampleAction.ECHO.value] = sync_echo

    run_task = asyncio.create_task(handler.run())
    await conn.send_peer_request("echo", {"a": 1}, seq_id=11)
    [response] = await conn.sent_messages(1)

    assert response["seq_id"] == 11
    assert response["data"] == {"echoed": {"a": 1}}

    await conn.close_peer()
    await run_task


@pytest.mark.asyncio
async def test_call_action_wraps_unexpected_future_error():
    conn = ProtocolConnection()
    handler = Handler(conn)

    call_task = asyncio.create_task(
        handler.call_action(SampleAction.ECHO, {}, timeout=1)
    )
    [request] = await conn.sent_messages(1)

    # An arbitrary exception delivered on the waiter (not a normal ActionResponse)
    # is wrapped as ActionCallError instead of leaking the raw exception type.
    handler.resp_waiters[request["seq_id"]].set_exception(RuntimeError("kaboom"))

    with pytest.raises(ActionCallError, match="RuntimeError: kaboom"):
        await call_task

    assert handler.resp_waiters == {}


# ---------------------------------------------------------------------------
# Streaming error / timeout / cancellation paths in call_action_generator.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_action_generator_raises_on_error_chunk():
    conn = ProtocolConnection()
    handler = Handler(conn)

    captured: dict[str, str] = {}

    async def consume():
        try:
            async for _ in handler.call_action_generator(
                SampleAction.STREAM, {}, timeout=1
            ):
                pass
        except ActionCallError as exc:
            captured["error"] = str(exc)

    task = asyncio.create_task(consume())
    [request] = await conn.sent_messages(1)
    queue = handler.resp_queues[request["seq_id"]]
    await queue.put(
        ActionResponse(seq_id=request["seq_id"], code=1, message="stream boom", data={})
    )

    await task
    assert captured["error"] == "stream boom"
    assert handler.resp_queues == {}


@pytest.mark.asyncio
async def test_call_action_generator_times_out_without_response():
    conn = ProtocolConnection()
    handler = Handler(conn)

    async def consume():
        async for _ in handler.call_action_generator(
            SampleAction.STREAM, {}, timeout=0.01
        ):
            pass

    with pytest.raises(ActionCallTimeoutError, match="Action stream call timed out"):
        await consume()

    assert handler.resp_queues == {}


@pytest.mark.asyncio
async def test_call_action_generator_stops_on_cancellation():
    conn = ProtocolConnection()
    handler = Handler(conn)

    async def consume():
        async for _ in handler.call_action_generator(
            SampleAction.STREAM, {}, timeout=5
        ):
            pass

    task = asyncio.create_task(consume())
    [request] = await conn.sent_messages(1)  # generator is now blocked on queue.get
    assert request["seq_id"] in handler.resp_queues

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # The generator's finally clause clears its queue regardless of how it exits.
    assert handler.resp_queues == {}


# ---------------------------------------------------------------------------
# Inbound file transfer: the __file_chunk handler reassembles chunks on disk,
# then read_local_file / delete_local_file round-trip them.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_chunk_action_reassembles_file_and_read_delete_roundtrip(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    conn = ProtocolConnection()
    handler = Handler(conn)

    payload = b"the quick brown fox jumps over the lazy dog" * 3
    file_key = "roundtrip.bin"
    chunk_handler = handler.actions[CommonAction.FILE_CHUNK.value]

    size = len(payload)
    step = (size + 2) // 3
    pieces = [payload[i : i + step] for i in range(0, size, step)]
    assert len(pieces) == 3  # exercises both the last-chunk and non-last branches

    for index, piece in enumerate(pieces):
        resp = await chunk_handler(
            {
                "file_key": file_key,
                "chunk_base64": base64.b64encode(piece).decode("utf-8"),
                "chunk_index": index,
                "chunk_amount": len(pieces),
            }
        )
        assert isinstance(resp, ActionResponse)
        assert resp.code == 0

    assert await handler.read_local_file(file_key) == payload

    # Delete once, then again: the second call must swallow FileNotFoundError.
    await handler.delete_local_file(file_key)
    await handler.delete_local_file(file_key)


@pytest.mark.asyncio
async def test_call_action_generator_wraps_unexpected_error():
    conn = ProtocolConnection()
    handler = Handler(conn)

    captured: dict[str, str] = {}

    async def consume():
        try:
            async for _ in handler.call_action_generator(
                SampleAction.STREAM, {}, timeout=1
            ):
                pass
        except ActionCallError as exc:
            captured["error"] = str(exc)

    task = asyncio.create_task(consume())
    [request] = await conn.sent_messages(1)
    # A malformed queue item (has no `.code`) is wrapped as ActionCallError,
    # mirroring the same guard in call_action.
    await handler.resp_queues[request["seq_id"]].put(object())  # type: ignore[arg-type]

    await task
    assert "AttributeError" in captured["error"]
    assert handler.resp_queues == {}


@pytest.mark.asyncio
async def test_run_dispatches_file_chunk_action_and_writes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = ProtocolConnection()
    handler = Handler(conn)

    run_task = asyncio.create_task(handler.run())

    payload = b"streamed-through-run"
    file_key = "via-run.bin"
    await conn.send_peer_request(
        CommonAction.FILE_CHUNK.value,
        {
            "file_key": file_key,
            "chunk_base64": base64.b64encode(payload).decode("utf-8"),
            "chunk_index": 0,
            "chunk_amount": 1,
        },
        seq_id=21,
    )
    [response] = await conn.sent_messages(1)
    assert response["seq_id"] == 21
    assert response["code"] == 0

    # The __file_chunk action was dispatched through run() and written to disk.
    assert await handler.read_local_file(file_key) == payload

    await conn.close_peer()
    await run_task


@pytest.mark.asyncio
async def test_run_ignores_malformed_message_without_crashing():
    conn = ProtocolConnection()
    handler = Handler(conn)

    @handler.action(SampleAction.ECHO)
    async def echo(data):
        return ActionResponse.success(data)

    run_task = asyncio.create_task(handler.run())

    # A message with neither "action" nor "code" is silently ignored...
    await conn.incoming.put(json.dumps({"seq_id": 1, "unexpected": "shape"}))

    # ...and the loop keeps serving subsequent requests.
    await conn.send_peer_request("echo", {"alive": True}, seq_id=2)
    [response] = await conn.sent_messages(1)
    assert response["seq_id"] == 2
    assert response["data"] == {"alive": True}

    await conn.close_peer()
    await run_task
