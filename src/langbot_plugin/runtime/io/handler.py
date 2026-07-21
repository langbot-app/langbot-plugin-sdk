from __future__ import annotations

import abc
import asyncio
import json
from typing import (
    Callable,
    Any,
    Coroutine,
    AsyncGenerator,
    Union,
    AsyncIterator,
)
import traceback
import random
import os
import hashlib
import base64
import uuid
import contextlib
import aiofiles
import aiofiles.os
import logging
from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.req import ActionRequest
from langbot_plugin.entities.io.resp import ActionResponse, ChunkStatus
from langbot_plugin.entities.io.errors import (
    ConnectionClosedError,
    ActionCallTimeoutError,
    ActionCallError,
)
from langbot_plugin.entities.io.actions.enums import ActionType, CommonAction

logger = logging.getLogger(__name__)

FILE_STORAGE_DIR = "data/temp/lbp"
FILE_CHUNK_LENGTH = 1024 * 16  # 16KB
MAX_INFLIGHT_ACTIONS = 128
MAX_STREAM_QUEUE_SIZE = 128


class Handler(abc.ABC):
    """The abstract base class for all handlers."""

    name: str = "Handler"

    conn: connection.Connection

    actions: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]]

    resp_waiters: dict[int, asyncio.Future[ActionResponse]] = {}
    resp_queues: dict[int, asyncio.Queue[ActionResponse | BaseException]] = {}

    seq_id_index: int = 0

    _disconnect_callback: Callable[[Handler], Coroutine[Any, Any, bool]] | None

    def __init__(
        self,
        connection: connection.Connection,
        disconnect_callback: Callable[[Handler], Coroutine[Any, Any, bool]]
        | None = None,
    ):
        self.conn = connection
        self.actions = {}
        self.seq_id_index = random.randint(0, 100000)
        self.resp_waiters = {}
        self.resp_queues = {}
        self._action_tasks: set[asyncio.Task[None]] = set()
        self._closed = False
        self._close_error: ConnectionClosedError | None = None

        self._disconnect_callback = disconnect_callback

        os.makedirs(FILE_STORAGE_DIR, exist_ok=True)

        @self.action(CommonAction.FILE_CHUNK)
        async def file_chunk(data: dict[str, Any]) -> ActionResponse:
            file_key = data["file_key"]
            chunk_base64 = data["chunk_base64"]
            chunk_index = data["chunk_index"]
            chunk_amount = data["chunk_amount"]
            # append the chunk to the file
            async with aiofiles.open(
                os.path.join(FILE_STORAGE_DIR, file_key), "ab"
            ) as f:
                await f.write(base64.b64decode(chunk_base64))
            if chunk_index == chunk_amount - 1:
                return ActionResponse.success({})
            else:
                return ActionResponse.success({})

    def set_disconnect_callback(
        self,
        disconnect_callback: Callable[[Handler], Coroutine[Any, Any, bool]]
        | None = None,
    ):
        self._disconnect_callback = disconnect_callback

    async def run(self) -> None:
        disconnect_error = ConnectionClosedError("Connection closed")
        try:
            while True:
                try:
                    message = await self.conn.receive()
                except ConnectionClosedError as exc:
                    disconnect_error = exc
                    # Requests sent on the old transport cannot be completed by
                    # a replacement connection, even when the handler itself is
                    # reused by a reconnect callback.
                    self._fail_pending(exc)
                    if self._disconnect_callback is not None:
                        reconnected = await self._disconnect_callback(self)
                        if reconnected:
                            continue
                    break
                if message is None:
                    continue

                try:
                    req_data = json.loads(message)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Ignored malformed runtime message: %s", exc)
                    continue
                if not isinstance(req_data, dict):
                    logger.warning("Ignored non-object runtime message")
                    continue

                seq_id = req_data.get("seq_id", -1)
                if "code" in req_data:
                    await self._route_response(seq_id, req_data)
                    continue

                if "action" not in req_data:
                    logger.warning("Ignored runtime message without action or code")
                    continue

                if len(self._action_tasks) >= MAX_INFLIGHT_ACTIONS:
                    await self._send_overloaded_response(seq_id)
                    continue

                task = asyncio.create_task(self._handle_action(req_data))
                self._action_tasks.add(task)
                task.add_done_callback(self._action_task_done)
        finally:
            self._closed = True
            self._close_error = disconnect_error
            self._fail_pending(disconnect_error)
            await self._cancel_action_tasks()

    async def close(self) -> None:
        """Close the transport and deterministically release connection-owned work."""
        if self._closed:
            return
        self._closed = True
        error = ConnectionClosedError("Connection closed by local runtime")
        self._close_error = error
        self._fail_pending(error)
        try:
            await self.conn.close()
        finally:
            await self._cancel_action_tasks()

    async def _route_response(self, seq_id: int, req_data: dict[str, Any]) -> None:
        try:
            response = ActionResponse.model_validate(req_data)
        except Exception as exc:
            logger.warning("Ignored malformed runtime response: %s", exc)
            return
        waiter = self.resp_waiters.get(seq_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(response)

        queue = self.resp_queues.get(seq_id)
        if queue is not None:
            try:
                queue.put_nowait(response)
            except asyncio.QueueFull:
                # A stalled stream consumer must not block response routing for
                # every other action sharing this connection.
                self.resp_queues.pop(seq_id, None)
                while not queue.empty():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                queue.put_nowait(
                    ActionCallError(
                        "Streaming action consumer is too slow; response buffer full"
                    )
                )

    async def _handle_action(self, req_data: dict[str, Any]) -> None:
        seq_id = req_data.get("seq_id", -1)
        action_name = str(req_data["action"])
        try:
            if action_name not in self.actions:
                raise ValueError(f"Action {action_name} not found")

            response = self.actions[action_name](req_data["data"])
            if not isinstance(response, AsyncGenerator):
                if isinstance(response, Coroutine):
                    response = await response
                response.seq_id = seq_id
                await self.conn.send(json.dumps(response.model_dump()))
            else:
                async for chunk in response:
                    assert isinstance(chunk, ActionResponse)
                    chunk.seq_id = seq_id
                    chunk.chunk_status = ChunkStatus.CONTINUE
                    await self.conn.send(json.dumps(chunk.model_dump()))

                end_response = ActionResponse.success({})
                end_response.seq_id = seq_id
                end_response.chunk_status = ChunkStatus.END
                await self.conn.send(json.dumps(end_response.model_dump()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            traceback.print_exc()
            error_response = ActionResponse.error(
                f"{exc.__class__.__name__}: {str(exc)}"
            )
            error_response.seq_id = seq_id
            with contextlib.suppress(ConnectionClosedError):
                await self.conn.send(json.dumps(error_response.model_dump()))
        finally:
            if not action_name.startswith("__"):
                logger.info("[Action] %s", action_name)

    async def _send_overloaded_response(self, seq_id: int) -> None:
        response = ActionResponse.error(
            f"Runtime connection is busy (max {MAX_INFLIGHT_ACTIONS} concurrent actions)"
        )
        response.seq_id = seq_id
        # The receive loop will observe a closed connection and run the normal
        # disconnect/reconnect path; don't bypass it if this best-effort reply
        # races with transport loss.
        with contextlib.suppress(ConnectionClosedError):
            await self.conn.send(json.dumps(response.model_dump()))

    def _action_task_done(self, task: asyncio.Task[None]) -> None:
        self._action_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Runtime action task failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    def _fail_pending(self, error: ConnectionClosedError) -> None:
        for waiter in list(self.resp_waiters.values()):
            if not waiter.done():
                waiter.set_exception(error)

        for queue in list(self.resp_queues.values()):
            while queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(error)

    async def _cancel_action_tasks(self) -> None:
        tasks = list(self._action_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._action_tasks.clear()

    async def call_action(
        self, action: ActionType, data: dict[str, Any], timeout: float = 15.0
    ) -> dict[str, Any]:
        """Actively call an action provided by the peer, and wait for the response."""
        self.seq_id_index += 1
        this_seq_id = self.seq_id_index
        request = ActionRequest.make_request(this_seq_id, action.value, data)
        # wait for response
        if self._closed:
            raise self._close_error or ConnectionClosedError("Connection closed")
        future = asyncio.get_running_loop().create_future()
        self.resp_waiters[this_seq_id] = future
        try:
            await self.conn.send(json.dumps(request.model_dump()))
            response = await asyncio.wait_for(future, timeout)
            if response.code != 0:
                raise ActionCallError(f"{response.message}")
            return response.data
        except asyncio.TimeoutError:
            raise ActionCallTimeoutError(f"Action {action.value} call timed out")
        except ActionCallError:
            raise
        except ConnectionClosedError:
            raise
        except Exception as e:
            raise ActionCallError(f"{e.__class__.__name__}: {str(e)}")
        finally:
            if this_seq_id in self.resp_waiters:
                del self.resp_waiters[this_seq_id]
            if this_seq_id in self.resp_queues:
                del self.resp_queues[this_seq_id]

    async def call_action_generator(
        self, action: ActionType, data: dict[str, Any], timeout: float = 15.0
    ) -> AsyncIterator[dict[str, Any]]:
        self.seq_id_index += 1
        this_seq_id = self.seq_id_index
        request = ActionRequest.make_request(this_seq_id, action.value, data)

        # Create a queue for streaming responses
        if self._closed:
            raise self._close_error or ConnectionClosedError("Connection closed")
        queue = asyncio.Queue[ActionResponse | BaseException](
            maxsize=MAX_STREAM_QUEUE_SIZE
        )
        self.resp_queues[this_seq_id] = queue

        try:
            await self.conn.send(json.dumps(request.model_dump()))
            while True:
                try:
                    response = await asyncio.wait_for(queue.get(), timeout)
                    if isinstance(response, BaseException):
                        raise response
                    if response.code != 0:
                        raise ActionCallError(f"{response.message}")

                    if response.chunk_status == ChunkStatus.CONTINUE:
                        yield response.data
                    elif response.chunk_status == ChunkStatus.END:
                        break
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError:
                    raise ActionCallTimeoutError(
                        f"Action {action.value} call timed out"
                    )
                except ActionCallError:
                    raise
                except ConnectionClosedError:
                    raise
                except Exception as e:
                    raise ActionCallError(f"{e.__class__.__name__}: {str(e)}")
        finally:
            if this_seq_id in self.resp_queues:
                del self.resp_queues[this_seq_id]

    # decorator to register an action
    def action(
        self, name: ActionType
    ) -> Callable[
        [
            Callable[
                [dict[str, Any]],
                Coroutine[
                    Any,
                    Any,
                    Union[ActionResponse, AsyncGenerator[ActionResponse, None]],
                ],
            ]
        ],
        Callable[
            [dict[str, Any]],
            Coroutine[
                Any, Any, Union[ActionResponse, AsyncGenerator[ActionResponse, None]]
            ],
        ],
    ]:
        def decorator(
            func: Callable[
                [dict[str, Any]],
                Coroutine[
                    Any,
                    Any,
                    Union[ActionResponse, AsyncGenerator[ActionResponse, None]],
                ],
            ],
        ) -> Callable[
            [dict[str, Any]],
            Coroutine[
                Any, Any, Union[ActionResponse, AsyncGenerator[ActionResponse, None]]
            ],
        ]:
            self.actions[name.value] = func
            return func

        return decorator

    # ====== file transfer ======
    async def send_file(self, file_bytes: bytes, file_extension: str) -> str:
        """Send a file to the peer, chunk by chunk, in base64."""
        hash_value = hashlib.sha256(file_bytes).hexdigest()[:16]
        extension = file_extension.strip(".")
        suffix = f".{extension}" if extension else ""
        file_key = f"{hash_value}-{uuid.uuid4().hex}{suffix}"
        file_length = len(file_bytes)
        chunk_amount = max(
            1, (file_length + FILE_CHUNK_LENGTH - 1) // FILE_CHUNK_LENGTH
        )
        for i in range(chunk_amount):
            chunk_bytes = file_bytes[
                i * FILE_CHUNK_LENGTH : (i + 1) * FILE_CHUNK_LENGTH
            ]
            chunk_base64 = base64.b64encode(chunk_bytes).decode("utf-8")
            # response = await self.conn.send(json.dumps({
            #     "action": CommonAction.FILE_CHUNK.value,
            #     "data": {
            #         "file_key": file_key,
            #         "file_length": file_length,
            #         "chunk_base64": chunk_base64,
            #         "chunk_index": i,
            #         "chunk_amount": chunk_amount,
            #         "chunk_size": len(chunk_bytes),
            #     }
            # }))
            await self.call_action(
                CommonAction.FILE_CHUNK,
                {
                    "file_key": file_key,
                    "file_length": file_length,
                    "chunk_base64": chunk_base64,
                    "chunk_index": i,
                    "chunk_amount": chunk_amount,
                    "chunk_size": len(chunk_bytes),
                },
            )
        return file_key

    async def read_local_file(self, file_key: str) -> bytes:
        async with aiofiles.open(os.path.join(FILE_STORAGE_DIR, file_key), "rb") as f:
            return await f.read()

    async def delete_local_file(self, file_key: str) -> None:
        try:
            await aiofiles.os.remove(os.path.join(FILE_STORAGE_DIR, file_key))
        except FileNotFoundError:
            return
