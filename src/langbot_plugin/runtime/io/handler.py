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
import random
import os
import hashlib
import base64
import uuid
import contextlib
import contextvars
import re
import aiofiles
import aiofiles.os
import logging
from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.req import ActionRequest
from langbot_plugin.entities.io.context import (
    ActionEnvelopeContext,
    InstallationBinding,
    parse_action_envelope_context,
)
from langbot_plugin.entities.io.resp import ActionResponse, ChunkStatus
from langbot_plugin.entities.io.errors import (
    ConnectionClosedError,
    ActionCallTimeoutError,
    ActionCallError,
)
from langbot_plugin.entities.io.actions.enums import ActionType, CommonAction
from langbot_plugin.runtime.security import PLUGIN_RUNTIME_PROFILE_ENV
from langbot_plugin.runtime.bounded_executor import blocking_work_scope

logger = logging.getLogger(__name__)

FILE_STORAGE_DIR = "data/temp/lbp"
SHARED_WORKER_FILE_STORAGE_DIR = "/tmp/lbp-rpc"
FILE_CHUNK_LENGTH = 1024 * 16  # 16KB
MAX_INFLIGHT_ACTIONS = 128
MAX_STREAM_QUEUE_SIZE = 128
MAX_ACTIVE_FILE_TRANSFERS = 128
MAX_PROTOCOL_ERROR_CHARS = 4096
_SAFE_FILE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_SAFE_FILE_EXTENSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def _file_storage_path(
    file_key: str,
    file_storage_dir: str | os.PathLike[str] = FILE_STORAGE_DIR,
) -> str:
    """Resolve one opaque transfer key without accepting path syntax."""

    if not isinstance(file_key, str):
        raise ValueError("Invalid file transfer key")
    key = file_key.strip()
    if (
        not key
        or key != file_key
        or os.path.isabs(key)
        or "/" in key
        or "\\" in key
        or ".." in key
        or os.path.basename(key) != key
        or _SAFE_FILE_KEY_PATTERN.fullmatch(key) is None
    ):
        raise ValueError("Invalid file transfer key")
    return os.path.join(os.fspath(file_storage_dir), key)


class Handler(abc.ABC):
    """The abstract base class for all handlers."""

    name: str = "Handler"

    conn: connection.Connection

    actions: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]]

    resp_waiters: dict[int, asyncio.Future[ActionResponse]] = {}
    resp_queues: dict[int, asyncio.Queue[ActionResponse | BaseException]] = {}

    seq_id_index: int = 0

    _disconnect_callback: Callable[[Handler], Coroutine[Any, Any, bool]] | None

    _bound_action_context: ActionEnvelopeContext | None
    _current_action_context: contextvars.ContextVar[ActionEnvelopeContext | None]

    def __init__(
        self,
        connection: connection.Connection,
        disconnect_callback: Callable[[Handler], Coroutine[Any, Any, bool]]
        | None = None,
        *,
        file_storage_dir: str | os.PathLike[str] | None = None,
        max_file_bytes: int | None = None,
    ):
        self.conn = connection
        self.actions = {}
        self.seq_id_index = random.randint(0, 100000)
        self.resp_waiters = {}
        self.resp_queues = {}
        self._action_tasks: set[asyncio.Task[None]] = set()
        self._closed = False
        self._close_error: ConnectionClosedError | None = None
        self._bound_action_context = None
        self._current_action_context = contextvars.ContextVar(
            f"{self.__class__.__name__}_{id(self)}_action_context",
            default=None,
        )

        if file_storage_dir is None:
            runtime_profile = os.environ.get(PLUGIN_RUNTIME_PROFILE_ENV, "oss_dev")
            file_storage_dir = (
                SHARED_WORKER_FILE_STORAGE_DIR
                if runtime_profile == "shared"
                else FILE_STORAGE_DIR
            )
        self.file_storage_dir = os.fspath(file_storage_dir)
        if max_file_bytes is not None and (
            isinstance(max_file_bytes, bool)
            or not isinstance(max_file_bytes, int)
            or max_file_bytes <= 0
        ):
            raise ValueError("max_file_bytes must be a positive integer")
        self.max_file_bytes = max_file_bytes
        self._file_transfer_lock = asyncio.Lock()
        self._owned_transfer_files: set[str] = set()

        self._disconnect_callback = disconnect_callback

        os.makedirs(self.file_storage_dir, mode=0o700, exist_ok=True)
        os.chmod(self.file_storage_dir, 0o700)

        @self.action(CommonAction.FILE_CHUNK)
        async def file_chunk(data: dict[str, Any]) -> ActionResponse:
            file_path = _file_storage_path(
                data["file_key"],
                self.file_storage_dir,
            )
            chunk_base64 = data["chunk_base64"]
            chunk_index = data["chunk_index"]
            chunk_amount = data["chunk_amount"]
            if (
                not isinstance(chunk_base64, str)
                or len(chunk_base64) > ((FILE_CHUNK_LENGTH + 2) // 3) * 4
            ):
                raise ValueError("File transfer chunk exceeds the protocol limit")
            if (
                isinstance(chunk_index, bool)
                or not isinstance(chunk_index, int)
                or isinstance(chunk_amount, bool)
                or not isinstance(chunk_amount, int)
                or chunk_amount <= 0
                or chunk_index < 0
                or chunk_index >= chunk_amount
            ):
                raise ValueError("Invalid file chunk position")
            chunk_bytes = base64.b64decode(chunk_base64, validate=True)
            if len(chunk_bytes) > FILE_CHUNK_LENGTH:
                raise ValueError("File transfer chunk exceeds the protocol limit")
            async with self._file_transfer_lock:
                if (
                    data["file_key"] not in self._owned_transfer_files
                    and len(self._owned_transfer_files) >= MAX_ACTIVE_FILE_TRANSFERS
                ):
                    raise ValueError("Active file transfer capacity reached")
                self._owned_transfer_files.add(data["file_key"])
                # The first chunk replaces stale partial data for the same
                # opaque transfer id; later chunks append. Runtime-side
                # installation handlers cap the aggregate bytes written on
                # behalf of an untrusted worker so protocol transfer cannot
                # bypass the worker's per-file policy.
                mode = "wb" if chunk_index == 0 else "ab"
                existing_size = 0
                if mode == "ab":
                    try:
                        existing_size = os.path.getsize(file_path)
                    except FileNotFoundError:
                        pass
                resulting_size = (
                    len(chunk_bytes)
                    if mode == "wb"
                    else existing_size + len(chunk_bytes)
                )
                if (
                    self.max_file_bytes is not None
                    and resulting_size > self.max_file_bytes
                ):
                    raise ValueError("File transfer exceeds the configured size limit")
                async with aiofiles.open(file_path, mode) as f:
                    await f.write(chunk_bytes)
            return ActionResponse.success({})

    def _message_blocking_scope(
        self,
        action_context: ActionEnvelopeContext | None = None,
    ) -> str | None:
        context = (
            action_context
            or self._current_action_context.get()
            or self._bound_action_context
        )
        return getattr(context, "workspace_uuid", None)

    async def _decode_message(self, message: str) -> Any:
        """Parse peer JSON outside the shared event loop with tenant fairness."""

        with blocking_work_scope(self._message_blocking_scope()):
            return await asyncio.to_thread(json.loads, message)

    async def _encode_message(
        self,
        payload: Any,
        *,
        action_context: ActionEnvelopeContext | None = None,
    ) -> str:
        """Serialize protocol JSON outside the shared event loop."""

        with blocking_work_scope(
            self._message_blocking_scope(action_context),
        ):
            return await asyncio.to_thread(
                lambda: json.dumps(
                    payload.model_dump() if hasattr(payload, "model_dump") else payload
                )
            )

    async def _validate_message_model(
        self,
        model_type: Any,
        payload: Any,
    ) -> Any:
        """Run potentially deep Pydantic validation outside the event loop."""

        with blocking_work_scope(self._message_blocking_scope()):
            return await asyncio.to_thread(model_type.model_validate, payload)

    async def _send_message(
        self,
        payload: Any,
        *,
        action_context: ActionEnvelopeContext | None = None,
    ) -> None:
        """Keep serialization and transport chunking in one tenant scope."""

        with blocking_work_scope(
            self._message_blocking_scope(action_context),
        ):
            encoded = await self._encode_message(
                payload,
                action_context=action_context,
            )
            await self.conn.send(encoded)

    async def _format_protocol_error(self, exc: BaseException) -> str:
        def render() -> str:
            message = str(exc)
            if len(message) > MAX_PROTOCOL_ERROR_CHARS:
                message = (
                    message[:MAX_PROTOCOL_ERROR_CHARS]
                    + "... [protocol error truncated]"
                )
            return f"{exc.__class__.__name__}: {message}"

        with blocking_work_scope(self._message_blocking_scope()):
            return await asyncio.to_thread(render)

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
                    req_data = await self._decode_message(message)
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
            await self._cleanup_owned_transfers()

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
            await self._cleanup_owned_transfers()

    async def _route_response(self, seq_id: int, req_data: dict[str, Any]) -> None:
        try:
            response = await self._validate_message_model(
                ActionResponse,
                req_data,
            )
        except Exception as exc:
            logger.warning(
                "Ignored malformed runtime response: %s",
                exc.__class__.__name__,
            )
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
        action_name = str(req_data.get("action", ""))
        context_token = None
        try:
            request = await self._validate_message_model(
                ActionRequest,
                req_data,
            )
            action_name = request.action
            if action_name not in self.actions:
                raise ValueError(f"Action {action_name} not found")

            action_context = self.validate_inbound_action_context(
                action_name,
                request.context,
            )
            context_token = self._current_action_context.set(action_context)

            with blocking_work_scope(getattr(action_context, "workspace_uuid", None)):
                response = self.actions[action_name](request.data)
                if not isinstance(response, AsyncGenerator):
                    if isinstance(response, Coroutine):
                        response = await response
                    response.seq_id = seq_id
                    await self._send_message(response)
                else:
                    async for chunk in response:
                        assert isinstance(chunk, ActionResponse)
                        chunk.seq_id = seq_id
                        chunk.chunk_status = ChunkStatus.CONTINUE
                        await self._send_message(chunk)

                    end_response = ActionResponse.success({})
                    end_response.seq_id = seq_id
                    end_response.chunk_status = ChunkStatus.END
                    await self._send_message(end_response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Runtime action %s failed with %s",
                action_name or "<unknown>",
                exc.__class__.__name__,
            )
            error_response = ActionResponse.error(
                await self._format_protocol_error(exc)
            )
            error_response.seq_id = seq_id
            with contextlib.suppress(ConnectionClosedError):
                await self._send_message(error_response)
        finally:
            if context_token is not None:
                self._current_action_context.reset(context_token)
            if action_name and not action_name.startswith("__"):
                logger.debug("[Action] %s", action_name)

    async def _send_overloaded_response(self, seq_id: int) -> None:
        response = ActionResponse.error(
            f"Runtime connection is busy (max {MAX_INFLIGHT_ACTIONS} concurrent actions)"
        )
        response.seq_id = seq_id
        with contextlib.suppress(ConnectionClosedError):
            await self._send_message(response)

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

    def cancel_inflight_messages(self) -> None:
        """Cancel peer requests already accepted by this handler."""

        for action_task in tuple(self._action_tasks):
            action_task.cancel()

    async def call_action(
        self,
        action: ActionType,
        data: dict[str, Any],
        timeout: float = 15.0,
        action_context: ActionEnvelopeContext | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Actively call an action provided by the peer, and wait for the response."""
        self.seq_id_index += 1
        this_seq_id = self.seq_id_index
        request = ActionRequest.make_request(
            this_seq_id,
            action.value,
            data,
            resolved_context := self.resolve_outbound_action_context(action_context),
        )
        # wait for response
        if self._closed:
            raise self._close_error or ConnectionClosedError("Connection closed")
        future = asyncio.get_running_loop().create_future()
        self.resp_waiters[this_seq_id] = future
        try:
            await self._send_message(
                request,
                action_context=resolved_context,
            )
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
        self,
        action: ActionType,
        data: dict[str, Any],
        timeout: float = 15.0,
        action_context: ActionEnvelopeContext | dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.seq_id_index += 1
        this_seq_id = self.seq_id_index
        request = ActionRequest.make_request(
            this_seq_id,
            action.value,
            data,
            resolved_context := self.resolve_outbound_action_context(action_context),
        )

        # Create a queue for streaming responses
        if self._closed:
            raise self._close_error or ConnectionClosedError("Connection closed")
        queue = asyncio.Queue[ActionResponse | BaseException](
            maxsize=MAX_STREAM_QUEUE_SIZE
        )
        self.resp_queues[this_seq_id] = queue

        try:
            await self._send_message(
                request,
                action_context=resolved_context,
            )
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

    @property
    def bound_action_context(self) -> ActionEnvelopeContext | None:
        """Trusted context permanently associated with this connection."""

        return self._bound_action_context

    @property
    def current_action_context(self) -> ActionEnvelopeContext | None:
        """Context of the request currently executing in this asyncio task."""

        return self._current_action_context.get()

    def bind_action_context(
        self,
        action_context: ActionEnvelopeContext | dict[str, Any],
    ) -> ActionEnvelopeContext:
        """Bind this connection once to a fenced Workspace.

        The installation capability may be added once after LangBot resolves
        the installation from its trusted settings store.  Changing the
        Workspace, generation, or an existing installation is rejected.
        """

        context = parse_action_envelope_context(action_context)
        current = self._bound_action_context
        if current is not None:
            if not current.same_workspace(context):
                raise ValueError(
                    "Action connection cannot be rebound to another Workspace"
                )
            if (
                current.installation_uuid is not None
                and context.installation_uuid is None
            ):
                raise ValueError("Plugin installation binding cannot be removed")
            if (
                current.installation_uuid is not None
                and current.installation_uuid != context.installation_uuid
            ):
                raise ValueError(
                    "Action connection cannot be rebound to another plugin installation"
                )
            if isinstance(current, InstallationBinding) and (
                not isinstance(context, InstallationBinding) or context != current
            ):
                raise ValueError(
                    "Action connection cannot change installation revision or artifact"
                )

        self._bound_action_context = context
        return context

    def require_bound_action_context(self) -> ActionEnvelopeContext:
        """Return the trusted binding or fail instead of choosing a default."""

        if self._bound_action_context is None:
            raise ValueError("Plugin Runtime is not bound to a Workspace")
        return self._bound_action_context

    def validate_inbound_action_context(
        self,
        action: str,
        action_context: ActionEnvelopeContext | None,
    ) -> ActionEnvelopeContext | None:
        """Validate an inbound envelope against the connection binding.

        A bound connection remains compatible with old peers that omit the
        envelope: the connection binding supplies the context.  A peer cannot
        switch Workspace or placement generation by sending a new envelope.
        """

        del action
        bound = self._bound_action_context
        if bound is None:
            return action_context
        if action_context is not None:
            if not bound.same_workspace(action_context):
                raise ValueError("Action context does not match connection Workspace")
            if (
                bound.installation_uuid is not None
                and action_context.installation_uuid != bound.installation_uuid
            ):
                raise ValueError(
                    "Action context does not match connection plugin installation"
                )
            if isinstance(bound, InstallationBinding) and action_context != bound:
                raise ValueError(
                    "Action context does not match installation revision or artifact"
                )
        return bound

    def resolve_outbound_action_context(
        self,
        action_context: ActionEnvelopeContext | dict[str, Any] | None,
    ) -> ActionEnvelopeContext | None:
        """Resolve and validate the envelope for an outbound request."""

        if action_context is None:
            return self._bound_action_context

        context = parse_action_envelope_context(action_context)
        bound = self._bound_action_context
        if bound is not None:
            if not bound.same_workspace(context):
                raise ValueError(
                    "Outbound action context does not match connection Workspace"
                )
            if (
                bound.installation_uuid is not None
                and context.installation_uuid != bound.installation_uuid
            ):
                raise ValueError(
                    "Outbound action context does not match plugin installation"
                )
            if isinstance(bound, InstallationBinding) and context != bound:
                raise ValueError(
                    "Outbound action context does not match installation revision or artifact"
                )
        return context

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
        if self.max_file_bytes is not None and len(file_bytes) > self.max_file_bytes:
            raise ValueError("File transfer exceeds the configured size limit")
        hash_value = hashlib.sha256(file_bytes).hexdigest()[:16]
        if not isinstance(file_extension, str):
            raise ValueError("Invalid file transfer extension")
        extension = file_extension.strip(".")
        if extension and _SAFE_FILE_EXTENSION_PATTERN.fullmatch(extension) is None:
            raise ValueError("Invalid file transfer extension")
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
        file_path = _file_storage_path(file_key, self.file_storage_dir)
        if self.max_file_bytes is not None:
            try:
                file_size = await asyncio.to_thread(os.path.getsize, file_path)
            except FileNotFoundError:
                raise
            if file_size > self.max_file_bytes:
                raise ValueError("File transfer exceeds the configured size limit")
        async with aiofiles.open(
            file_path,
            "rb",
        ) as f:
            content = await f.read(
                self.max_file_bytes + 1 if self.max_file_bytes is not None else -1
            )
        if self.max_file_bytes is not None and len(content) > self.max_file_bytes:
            raise ValueError("File transfer exceeds the configured size limit")
        return content

    async def delete_local_file(self, file_key: str) -> None:
        async with self._file_transfer_lock:
            try:
                await aiofiles.os.remove(
                    _file_storage_path(file_key, self.file_storage_dir)
                )
            except FileNotFoundError:
                pass
            finally:
                self._owned_transfer_files.discard(file_key)

    async def _cleanup_owned_transfers(self) -> None:
        async with self._file_transfer_lock:
            file_keys = tuple(self._owned_transfer_files)
            self._owned_transfer_files.clear()
            for file_key in file_keys:
                try:
                    await aiofiles.os.remove(
                        _file_storage_path(file_key, self.file_storage_dir)
                    )
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    logger.warning(
                        "Failed to clean runtime transfer file %s: %s",
                        file_key,
                        exc,
                    )
