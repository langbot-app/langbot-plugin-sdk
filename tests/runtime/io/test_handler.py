from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import stat

import pytest

from langbot_plugin.entities.io.actions.enums import ActionType, CommonAction
from langbot_plugin.entities.io.errors import (
    ActionCallError,
    ActionCallTimeoutError,
    ConnectionClosedError,
)
from langbot_plugin.entities.io.resp import ActionResponse, ChunkStatus
from langbot_plugin.entities.io.context import ActionContext, InstallationBinding
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io import handler as handler_module
from langbot_plugin.runtime.io.handler import FILE_CHUNK_LENGTH, Handler
from langbot_plugin.runtime.security import PLUGIN_RUNTIME_PROFILE_ENV
from langbot_plugin.runtime.bounded_executor import (
    current_blocking_work_scope,
)

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


class FailingSendConnection(QueueConnection):
    async def send(self, message: str) -> None:
        raise ConnectionClosedError("send failed")


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


def _action_context(workspace_uuid="workspace-a", installation_uuid=None):
    return ActionContext(
        instance_uuid="instance-1",
        workspace_uuid=workspace_uuid,
        placement_generation=5,
        installation_uuid=installation_uuid,
    )


@pytest.mark.asyncio
async def test_call_action_carries_bound_context_outside_data_payload():
    conn = QueueConnection()
    handler = Handler(conn)
    context = _action_context(installation_uuid="installation-1")
    handler.bind_action_context(context)

    task = asyncio.create_task(handler.call_action(SampleAction.ECHO, {}, timeout=1))
    [request] = await _wait_for_sent(conn)

    assert request["data"] == {}
    assert request["context"] == context.model_dump()

    handler.resp_waiters[request["seq_id"]].set_result(
        ActionResponse(seq_id=request["seq_id"], code=0, message="ok", data={})
    )
    await task


def test_handler_binding_is_idempotent_but_cannot_change_workspace_or_installation():
    handler = Handler(QueueConnection())
    workspace_binding = _action_context()

    assert handler.bind_action_context(workspace_binding) == workspace_binding
    assert handler.bind_action_context(workspace_binding) == workspace_binding

    installation_binding = workspace_binding.for_installation("installation-1")
    assert handler.bind_action_context(installation_binding) == installation_binding

    with pytest.raises(ValueError, match="another Workspace"):
        handler.bind_action_context(_action_context(workspace_uuid="workspace-b"))
    with pytest.raises(ValueError, match="another plugin installation"):
        handler.bind_action_context(
            workspace_binding.for_installation("installation-2")
        )
    with pytest.raises(ValueError, match="cannot be removed"):
        handler.bind_action_context(workspace_binding)


@pytest.mark.asyncio
async def test_handler_json_codec_uses_workspace_bounded_thread(monkeypatch):
    handler = Handler(QueueConnection())
    handler.bind_action_context(_action_context(workspace_uuid="workspace-a"))
    calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        calls.append((fn, current_blocking_work_scope()))
        return fn(*args, **kwargs)

    monkeypatch.setattr(handler_module.asyncio, "to_thread", fake_to_thread)

    assert await handler._decode_message('{"ok": true}') == {"ok": True}
    assert json.loads(await handler._encode_message({"ok": True})) == {
        "ok": True
    }
    assert calls[0] == (json.loads, "workspace-a")
    assert calls[1][1] == "workspace-a"
    assert len(calls) == 2


def test_handler_preserves_complete_installation_binding_and_rejects_downgrade():
    handler = Handler(QueueConnection())
    binding = InstallationBinding(
        instance_uuid="instance-1",
        workspace_uuid="workspace-a",
        placement_generation=5,
        installation_uuid="installation-1",
        runtime_revision=2,
        artifact_digest="a" * 64,
    )

    assert handler.bind_action_context(binding.model_dump()) == binding
    assert isinstance(handler.bound_action_context, InstallationBinding)
    with pytest.raises(ValueError, match="revision or artifact"):
        handler.bind_action_context(
            ActionContext(
                instance_uuid=binding.instance_uuid,
                workspace_uuid=binding.workspace_uuid,
                placement_generation=binding.placement_generation,
                installation_uuid=binding.installation_uuid,
            )
        )
    with pytest.raises(ValueError, match="revision or artifact"):
        handler.bind_action_context(binding.model_copy(update={"runtime_revision": 3}))


@pytest.mark.asyncio
async def test_run_exposes_validated_context_to_action_and_rejects_mismatch():
    conn = ProtocolConnection()
    handler = Handler(conn)
    binding = _action_context()
    handler.bind_action_context(binding)
    seen = []

    @handler.action(SampleAction.ECHO)
    async def echo(_data):
        seen.append(
            (
                handler.current_action_context,
                current_blocking_work_scope(),
            )
        )
        return ActionResponse.success({})

    run_task = asyncio.create_task(handler.run())
    await conn.send_peer_request("echo", {}, seq_id=1)
    [success] = await conn.sent_messages(1)
    assert success["code"] == 0
    assert seen == [(binding, binding.workspace_uuid)]

    await conn.send_peer_request(
        "echo",
        {},
        seq_id=2,
        action_context=_action_context(workspace_uuid="workspace-b"),
    )
    responses = await conn.sent_messages(2)
    assert responses[1]["code"] == 1
    assert "does not match connection Workspace" in responses[1]["message"]
    assert seen == [(binding, binding.workspace_uuid)]

    await conn.close_peer()
    await run_task


@pytest.mark.asyncio
async def test_call_action_timeout_cleans_waiter():
    conn = QueueConnection()
    handler = Handler(conn)

    with pytest.raises(ActionCallTimeoutError, match="Action echo call timed out"):
        await handler.call_action(SampleAction.ECHO, {}, timeout=0.01)

    assert handler.resp_waiters == {}


@pytest.mark.asyncio
async def test_call_action_send_failure_cleans_waiter_immediately():
    handler = Handler(FailingSendConnection())

    with pytest.raises(ConnectionClosedError, match="send failed"):
        await handler.call_action(SampleAction.ECHO, {}, timeout=10)

    assert handler.resp_waiters == {}


@pytest.mark.asyncio
async def test_disconnect_fails_pending_unary_and_stream_calls():
    conn = ProtocolConnection()
    handler = Handler(conn)
    run_task = asyncio.create_task(handler.run())
    unary = asyncio.create_task(handler.call_action(SampleAction.ECHO, {}, timeout=10))

    async def consume_stream():
        async for _ in handler.call_action_generator(
            SampleAction.STREAM, {}, timeout=10
        ):
            pass

    stream = asyncio.create_task(consume_stream())
    await conn.sent_messages(2)
    await conn.close_peer()

    with pytest.raises(ConnectionClosedError):
        await asyncio.wait_for(unary, timeout=0.5)
    with pytest.raises(ConnectionClosedError):
        await asyncio.wait_for(stream, timeout=0.5)
    await run_task
    assert handler.resp_waiters == {}
    assert handler.resp_queues == {}


@pytest.mark.asyncio
async def test_reconnect_still_fails_requests_from_old_transport():
    first = QueueConnection()
    second = QueueConnection()
    reconnects = 0

    async def reconnect(current_handler):
        nonlocal reconnects
        reconnects += 1
        if reconnects == 1:
            current_handler.conn = second
            return True
        return False

    handler = Handler(first, reconnect)
    run_task = asyncio.create_task(handler.run())
    old_call = asyncio.create_task(
        handler.call_action(SampleAction.ECHO, {}, timeout=10)
    )
    await _wait_for_sent(first)
    await first.incoming.put(ConnectionClosedError("old transport closed"))

    with pytest.raises(ConnectionClosedError, match="old transport closed"):
        await asyncio.wait_for(old_call, timeout=0.5)

    new_call = asyncio.create_task(
        handler.call_action(SampleAction.ECHO, {}, timeout=1)
    )
    [request] = await _wait_for_sent(second)
    await second.incoming.put(
        json.dumps(
            ActionResponse.success({"generation": 2})
            .model_copy(update={"seq_id": request["seq_id"]})
            .model_dump()
        )
    )
    assert await new_call == {"generation": 2}

    await second.incoming.put(ConnectionClosedError("done"))
    await run_task


@pytest.mark.asyncio
async def test_run_ignores_non_object_json_message():
    conn = QueueConnection()
    handler = Handler(conn)

    @handler.action(SampleAction.ECHO)
    async def echo(data):
        return ActionResponse.success(data)

    run_task = asyncio.create_task(handler.run())
    await conn.incoming.put("[]")
    await conn.incoming.put(
        json.dumps({"seq_id": 4, "action": "echo", "data": {"ok": True}})
    )
    [response] = await _wait_for_sent(conn)
    await conn.incoming.put(ConnectionClosedError("done"))
    await run_task

    assert response["data"] == {"ok": True}


@pytest.mark.asyncio
async def test_slow_inbound_action_does_not_block_outbound_response_routing():
    conn = ProtocolConnection()
    handler = Handler(conn)
    release = asyncio.Event()

    @handler.action(SampleAction.STREAM)
    async def slow_action(_data):
        await release.wait()
        return ActionResponse.success({})

    run_task = asyncio.create_task(handler.run())
    await conn.send_peer_request("stream", {}, seq_id=77)
    call_task = asyncio.create_task(
        handler.call_action(SampleAction.ECHO, {}, timeout=1)
    )
    [request] = await conn.sent_messages(1)
    await conn.send_peer_response(request["seq_id"], data={"ok": True})

    assert await asyncio.wait_for(call_task, timeout=0.5) == {"ok": True}
    release.set()
    await conn.sent_messages(2)
    await conn.close_peer()
    await run_task


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
    context = _action_context(installation_uuid="installation-1")
    handler.bind_action_context(context)
    chunks: list[dict] = []

    async def consume():
        async for chunk in handler.call_action_generator(
            SampleAction.STREAM, {}, timeout=1
        ):
            chunks.append(chunk)

    task = asyncio.create_task(consume())
    [request] = await _wait_for_sent(conn)
    assert request["context"] == context.model_dump()
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
    context = _action_context()
    handler.bind_action_context(context)
    seen_contexts = []

    @handler.action(SampleAction.STREAM)
    async def stream(_data):
        seen_contexts.append(handler.current_action_context)
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
    assert seen_contexts == [context]


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


def test_shared_worker_file_storage_uses_private_writable_tmp(tmp_path, monkeypatch):
    worker_tmp = tmp_path / "lbp-rpc"
    monkeypatch.setenv(PLUGIN_RUNTIME_PROFILE_ENV, "shared")
    monkeypatch.setattr(
        "langbot_plugin.runtime.io.handler.SHARED_WORKER_FILE_STORAGE_DIR",
        str(worker_tmp),
    )

    handler = Handler(QueueConnection())

    assert handler.file_storage_dir == str(worker_tmp)
    assert worker_tmp.is_dir()


def test_handler_file_storage_can_be_isolated_per_installation(tmp_path):
    first = Handler(
        QueueConnection(),
        file_storage_dir=tmp_path / "installation-a" / "rpc-transfer",
    )
    second = Handler(
        QueueConnection(),
        file_storage_dir=tmp_path / "installation-b" / "rpc-transfer",
    )

    assert first.file_storage_dir != second.file_storage_dir
    assert (tmp_path / "installation-a" / "rpc-transfer").is_dir()
    assert (tmp_path / "installation-b" / "rpc-transfer").is_dir()
    assert (
        stat.S_IMODE((tmp_path / "installation-a" / "rpc-transfer").stat().st_mode)
        == 0o700
    )


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
async def test_file_chunk_action_enforces_aggregate_handler_limit(tmp_path):
    handler = Handler(
        ProtocolConnection(),
        file_storage_dir=tmp_path / "rpc-transfer",
        max_file_bytes=5,
    )
    chunk_handler = handler.actions[CommonAction.FILE_CHUNK.value]
    base = {
        "file_key": "limited.bin",
        "chunk_amount": 2,
    }

    await chunk_handler(
        {
            **base,
            "chunk_base64": base64.b64encode(b"1234").decode("ascii"),
            "chunk_index": 0,
        }
    )
    with pytest.raises(ValueError, match="configured size limit"):
        await chunk_handler(
            {
                **base,
                "chunk_base64": base64.b64encode(b"56").decode("ascii"),
                "chunk_index": 1,
            }
        )

    assert await handler.read_local_file("limited.bin") == b"1234"


@pytest.mark.asyncio
async def test_file_chunk_action_rejects_oversized_chunk_before_decode(
    tmp_path,
    monkeypatch,
):
    handler = Handler(
        ProtocolConnection(),
        file_storage_dir=tmp_path,
        max_file_bytes=FILE_CHUNK_LENGTH * 2,
    )
    decode_called = False

    def fail_if_decoded(*args, **kwargs):
        nonlocal decode_called
        decode_called = True
        raise AssertionError("oversized payload must be rejected before decoding")

    monkeypatch.setattr(
        "langbot_plugin.runtime.io.handler.base64.b64decode",
        fail_if_decoded,
    )

    with pytest.raises(ValueError, match="protocol limit"):
        await handler.actions[CommonAction.FILE_CHUNK.value](
            {
                "file_key": "oversized.bin",
                "chunk_base64": "A" * ((((FILE_CHUNK_LENGTH + 2) // 3) * 4) + 1),
                "chunk_index": 0,
                "chunk_amount": 1,
            }
        )
    assert not decode_called


@pytest.mark.asyncio
async def test_file_chunk_action_bounds_active_transfers_and_close_cleans_files(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(handler_module, "MAX_ACTIVE_FILE_TRANSFERS", 2)
    handler = Handler(
        ProtocolConnection(),
        file_storage_dir=tmp_path,
        max_file_bytes=1024,
    )
    chunk_handler = handler.actions[CommonAction.FILE_CHUNK.value]

    async def write(file_key: str) -> None:
        await chunk_handler(
            {
                "file_key": file_key,
                "chunk_base64": base64.b64encode(b"x").decode("ascii"),
                "chunk_index": 0,
                "chunk_amount": 1,
            }
        )

    await write("first.bin")
    await write("second.bin")
    with pytest.raises(ValueError, match="transfer capacity"):
        await write("third.bin")

    await handler.delete_local_file("first.bin")
    await write("third.bin")
    await handler.close()

    assert not (tmp_path / "second.bin").exists()
    assert not (tmp_path / "third.bin").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_key",
    [
        "../secret.txt",
        "/tmp/secret.txt",
        "nested/secret.txt",
        r"nested\secret.txt",
        "opaque..txt",
        r"C:\secret.txt",
        " surrounded.txt ",
        123,
    ],
)
async def test_file_transfer_rejects_path_syntax(file_key, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    handler = Handler(ProtocolConnection())
    chunk_handler = handler.actions[CommonAction.FILE_CHUNK.value]

    with pytest.raises(ValueError, match="Invalid file transfer key"):
        await chunk_handler(
            {
                "file_key": file_key,
                "chunk_base64": base64.b64encode(b"secret").decode("utf-8"),
                "chunk_index": 0,
                "chunk_amount": 1,
            }
        )
    with pytest.raises(ValueError, match="Invalid file transfer key"):
        await handler.read_local_file(file_key)
    with pytest.raises(ValueError, match="Invalid file transfer key"):
        await handler.delete_local_file(file_key)


@pytest.mark.asyncio
async def test_send_file_rejects_extension_with_path_syntax(monkeypatch):
    handler = Handler(ProtocolConnection())

    with pytest.raises(ValueError, match="Invalid file transfer extension"):
        await handler.send_file(b"payload", "../txt")


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
