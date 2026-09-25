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
import logging
import stat
import threading
import weakref
from dataclasses import dataclass
from contextlib import contextmanager
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
from langbot_plugin.runtime.security import (
    PLUGIN_FILE_STORAGE_DIR_ENV,
    PLUGIN_RUNTIME_PROFILE_ENV,
)
from langbot_plugin.runtime.bounded_executor import (
    blocking_work_scope,
    run_blocking_cleanup,
    run_blocking_with_backpressure,
)

logger = logging.getLogger(__name__)
_ORIGINAL_ASYNCIO_TO_THREAD = asyncio.to_thread

FILE_STORAGE_DIR = "data/temp/lbp"
SHARED_WORKER_FILE_STORAGE_DIR = "/tmp/lbp-rpc"
FILE_CHUNK_LENGTH = 1024 * 16  # 16KB
MAX_INFLIGHT_ACTIONS = 128
MAX_RESERVED_ACTIONS = 4
MAX_STREAM_QUEUE_SIZE = 128
MAX_ACTIVE_FILE_TRANSFERS = 128
MAX_PROTOCOL_ERROR_CHARS = 4096
_SAFE_FILE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_SAFE_FILE_EXTENSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_TRANSFER_CAPABILITY_PATTERN = re.compile(
    r"^ft1_[0-9a-f]{64}(?:\.[A-Za-z0-9][A-Za-z0-9_-]{0,31})?$"
)
_TRANSFER_OWNER_DIR = ".transfer-owners"

_TRANSFER_LOCKS_GUARD = threading.Lock()
_TRANSFER_LOCKS: dict[tuple[str, str], tuple[threading.RLock, int]] = {}
_ACTIVE_TRANSFER_HANDLERS: dict[tuple[str, str], weakref.ReferenceType[Any]] = {}


@dataclass
class _TransferStage:
    namespace: str
    temp_name: str
    descriptor: int
    file_stat: os.stat_result
    transfer_context: ActionEnvelopeContext | None
    claim_id: str | None
    chunk_amount: int
    next_index: int = 0
    size: int = 0
    payload_published: bool = False
    owner_published: bool = False


async def _run_small_protocol_work(fn: Callable[..., Any], *args: Any) -> Any:
    if asyncio.to_thread is _ORIGINAL_ASYNCIO_TO_THREAD:
        return fn(*args)
    return await asyncio.to_thread(fn, *args)


def _validate_file_key(file_key: str) -> str:
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
    return key


def _transfer_namespace(action_context: ActionEnvelopeContext | None) -> str:
    if action_context is None:
        return "unbound"
    serialized_context = json.dumps(
        action_context.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized_context).hexdigest()


def _transfer_owner_record_name(file_key: str) -> str | None:
    if _TRANSFER_CAPABILITY_PATTERN.fullmatch(file_key) is None:
        return None
    return hashlib.sha256(file_key.encode("ascii")).hexdigest() + ".json"


@contextmanager
def _locked_transfer(root: str, file_key: str):
    """Serialize one capability across every handler sharing a process/root."""

    lock_key = (root, file_key)
    with _TRANSFER_LOCKS_GUARD:
        entry = _TRANSFER_LOCKS.get(lock_key)
        if entry is None:
            lock = threading.RLock()
            references = 0
        else:
            lock, references = entry
        _TRANSFER_LOCKS[lock_key] = (lock, references + 1)
    lock.acquire()
    try:
        yield lock_key
    finally:
        lock.release()
        with _TRANSFER_LOCKS_GUARD:
            current_lock, references = _TRANSFER_LOCKS[lock_key]
            if current_lock is lock and references == 1:
                del _TRANSFER_LOCKS[lock_key]
            else:
                _TRANSFER_LOCKS[lock_key] = (current_lock, references - 1)


def _active_transfer_handler(lock_key: tuple[str, str]) -> Handler | None:
    with _TRANSFER_LOCKS_GUARD:
        reference = _ACTIVE_TRANSFER_HANDLERS.get(lock_key)
        active = None if reference is None else reference()
        if reference is not None and active is None:
            _ACTIVE_TRANSFER_HANDLERS.pop(lock_key, None)
        return active


def _is_active_transfer_handler(lock_key: tuple[str, str], handler: Any) -> bool:
    return _active_transfer_handler(lock_key) is handler


def _set_active_transfer_handler(lock_key: tuple[str, str], active: Any | None) -> None:
    with _TRANSFER_LOCKS_GUARD:
        if active is None:
            _ACTIVE_TRANSFER_HANDLERS.pop(lock_key, None)
        else:
            _ACTIVE_TRANSFER_HANDLERS[lock_key] = weakref.ref(active)


def _clear_active_transfer_handler(lock_key: tuple[str, str], expected: Any) -> None:
    with _TRANSFER_LOCKS_GUARD:
        reference = _ACTIVE_TRANSFER_HANDLERS.get(lock_key)
        if reference is not None and reference() is expected:
            del _ACTIVE_TRANSFER_HANDLERS[lock_key]


def _open_transfer_directory(
    root_fd: int,
    directory_name: str,
    *,
    create: bool,
) -> int:
    """Open one child directory beneath the bound transfer root descriptor."""

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            directory_fd = os.open(
                directory_name,
                directory_flags | no_follow,
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(directory_name, mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            directory_fd = os.open(
                directory_name,
                directory_flags | no_follow,
                dir_fd=root_fd,
            )
        directory_stat = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_stat.st_mode):
            os.close(directory_fd)
            raise ValueError("Invalid file transfer capability")
        return directory_fd
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ValueError("Invalid file transfer capability") from None


def _prepare_transfer_root(root: str) -> tuple[str, int, os.stat_result]:
    """Create and bind the configured root to one exact directory inode."""

    lexical_root = os.path.abspath(root)
    components = lexical_root.split(os.sep)
    if len(components) <= 1:
        raise ValueError("Invalid file transfer root")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        current_fd = os.open(os.sep, directory_flags)
    except OSError:
        raise ValueError("Invalid file transfer root") from None
    try:
        for component in components[1:]:
            if not component:
                continue
            try:
                os.mkdir(component, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            try:
                next_fd = os.open(
                    component,
                    directory_flags | no_follow,
                    dir_fd=current_fd,
                )
            except OSError:
                raise ValueError("Invalid file transfer root") from None
            os.close(current_fd)
            current_fd = next_fd
        root_stat = os.fstat(current_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError("Invalid file transfer root")
        os.fchmod(current_fd, 0o700)
        path_stat = os.stat(lexical_root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(path_stat.st_mode)
            or path_stat.st_dev != root_stat.st_dev
            or path_stat.st_ino != root_stat.st_ino
        ):
            raise ValueError("Invalid file transfer root")
    except OSError:
        os.close(current_fd)
        raise ValueError("Invalid file transfer root") from None
    except BaseException:
        os.close(current_fd)
        raise
    return lexical_root, current_fd, root_stat


def _read_regular_at(
    root_fd: int,
    directory_name: str,
    file_name: str,
    *,
    private: bool = False,
    max_bytes: int | None = None,
) -> tuple[bytes, os.stat_result]:
    directory_fd = _open_transfer_directory(root_fd, directory_name, create=False)
    try:
        try:
            descriptor = os.open(
                file_name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                raise
            raise ValueError("Invalid file transfer capability") from None
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError("Invalid file transfer capability")
            if private and file_stat.st_mode & 0o077:
                raise ValueError("Invalid file transfer capability")
            if max_bytes is not None and file_stat.st_size > max_bytes:
                raise ValueError("File transfer exceeds the configured size limit")
            with os.fdopen(descriptor, "rb", closefd=False) as file:
                content = file.read(max_bytes + 1 if max_bytes is not None else -1)
            return content, file_stat
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)


def _file_storage_path(
    file_key: str,
    file_storage_dir: str | os.PathLike[str] = FILE_STORAGE_DIR,
    *,
    action_context: ActionEnvelopeContext | None = None,
    create_namespace: bool = False,
) -> str:
    """Resolve one opaque key inside its durable authority namespace."""

    key = _validate_file_key(file_key)
    namespace = _transfer_namespace(action_context)
    namespace_path = os.path.join(os.fspath(file_storage_dir), namespace)
    if create_namespace:
        _root, root_fd, _root_stat = _prepare_transfer_root(os.fspath(file_storage_dir))
        try:
            namespace_fd = _open_transfer_directory(root_fd, namespace, create=True)
            os.close(namespace_fd)
        finally:
            os.close(root_fd)
    return os.path.join(namespace_path, key)


def _transfer_owner_record_path(
    file_key: str,
    file_storage_dir: str | os.PathLike[str],
) -> str | None:
    """Return the exact durable owner record for an opaque transfer capability."""

    if not isinstance(file_key, str):
        return None
    record_name = _transfer_owner_record_name(file_key)
    if record_name is None:
        return None
    return os.path.join(os.fspath(file_storage_dir), _TRANSFER_OWNER_DIR, record_name)


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
        cancel_active_tasks_on_close: bool = False,
    ):
        if max_file_bytes is not None and (
            isinstance(max_file_bytes, bool)
            or not isinstance(max_file_bytes, int)
            or max_file_bytes <= 0
        ):
            raise ValueError("max_file_bytes must be a positive integer")
        self.conn = connection
        self.actions = {}
        self.seq_id_index = random.randint(0, 100000)
        self.resp_waiters = {}
        self.resp_queues = {}
        self._action_tasks: set[asyncio.Task[None]] = set()
        self._action_task_contexts: dict[
            asyncio.Task[None], ActionEnvelopeContext | None
        ] = {}
        self._active_tasks: set[asyncio.Task[None]] = set()
        # Reserved tasks remain in the common set for cancellation and accounting.
        self._reserved_action_tasks: set[asyncio.Task[None]] = set()
        # Kept for source compatibility; every connection-owned action is
        # cancelled when the transport terminates.
        self._cancel_active_tasks_on_close = cancel_active_tasks_on_close
        self._closed = False
        self._close_error: ConnectionClosedError | None = None
        self._bound_action_context = None
        self._current_action_context = contextvars.ContextVar(
            f"{self.__class__.__name__}_{id(self)}_action_context",
            default=None,
        )

        if file_storage_dir is None:
            runtime_profile = os.environ.get(PLUGIN_RUNTIME_PROFILE_ENV, "oss_dev")
            file_storage_dir = os.environ.get(PLUGIN_FILE_STORAGE_DIR_ENV) or (
                SHARED_WORKER_FILE_STORAGE_DIR
                if runtime_profile == "shared"
                else FILE_STORAGE_DIR
            )
        (
            self.file_storage_dir,
            self._file_storage_root_fd,
            root_stat,
        ) = _prepare_transfer_root(os.fspath(file_storage_dir))
        self._file_storage_root_identity = (root_stat.st_dev, root_stat.st_ino)
        self._file_storage_root_fd_closed = False
        self.max_file_bytes = max_file_bytes
        self._file_transfer_lock = asyncio.Lock()
        self._owned_transfer_files: set[str] = set()
        self._owned_transfer_records: set[str] = set()
        self._owned_transfer_contexts: dict[str, ActionEnvelopeContext | None] = {}
        self._owned_transfer_claims: dict[str, str | None] = {}
        self._owned_transfer_identities: dict[str, tuple[int, int]] = {}
        self._transfer_stages: dict[str, _TransferStage] = {}
        self._deleted_transfer_payloads: set[str] = set()

        self._disconnect_callback = disconnect_callback

        @self.action(CommonAction.FILE_CHUNK)
        async def file_chunk(data: dict[str, Any]) -> ActionResponse:
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
                transfer_context = self.resolve_effective_action_context()
                file_key = _validate_file_key(data["file_key"])
                await _run_small_protocol_work(
                    self._write_file_chunk,
                    file_key,
                    transfer_context,
                    chunk_bytes,
                    chunk_index,
                    chunk_amount,
                )
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
            return await run_blocking_with_backpressure(json.loads, message)

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
            return await run_blocking_with_backpressure(
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
            return await run_blocking_with_backpressure(
                model_type.model_validate, payload
            )

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
            return await run_blocking_with_backpressure(render)

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
                    # Do not let old inbound work reply on a replacement transport
                    # when this handler owns connection-scoped task cancellation.
                    if self._cancel_active_tasks_on_close:
                        await self._cancel_action_tasks()
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

                reserved = self._uses_reserved_admission(req_data)
                if reserved:
                    inflight = len(self._reserved_action_tasks)
                    limit = MAX_RESERVED_ACTIONS
                else:
                    inflight = len(self._action_tasks) - len(
                        self._reserved_action_tasks
                    )
                    limit = MAX_INFLIGHT_ACTIONS
                if inflight >= limit:
                    await self._send_overloaded_response(seq_id, limit=limit)
                    continue

                task = asyncio.create_task(self._handle_action(req_data))
                self._action_tasks.add(task)
                if reserved:
                    self._reserved_action_tasks.add(task)
                task.add_done_callback(self._action_task_done)
                if self._cancel_active_tasks_on_close:
                    self._active_tasks.add(task)
                    task.add_done_callback(self._active_tasks.discard)
        finally:
            self._closed = True
            self._close_error = disconnect_error
            self._fail_pending(disconnect_error)
            if self._cancel_active_tasks_on_close:
                await self._cancel_action_tasks()
            await self._cleanup_owned_transfers()
            if not self._owned_transfer_files:
                self._close_transfer_root_if_clean()

    async def close(self) -> None:
        """Close the transport and deterministically release connection-owned work."""
        if self._closed:
            if self._owned_transfer_files:
                await self._cleanup_owned_transfers()
            if not self._owned_transfer_files:
                self._close_transfer_root_if_clean()
            return
        self._closed = True
        error = ConnectionClosedError("Connection closed by local runtime")
        self._close_error = error
        self._fail_pending(error)
        try:
            await self.conn.close()
        finally:
            if self._cancel_active_tasks_on_close:
                await self._cancel_action_tasks()
            await self._cleanup_owned_transfers()
            if not self._owned_transfer_files:
                self._close_transfer_root_if_clean()

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
            current_task = asyncio.current_task()
            if current_task is not None:
                self._action_task_contexts[current_task] = action_context

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
            current_task = asyncio.current_task()
            if current_task is not None:
                self._action_task_contexts.pop(current_task, None)
            if action_name and not action_name.startswith("__"):
                logger.debug("[Action] %s", action_name)

    def _uses_reserved_admission(self, req_data: dict[str, Any]) -> bool:
        """Opt in to bounded control capacity, not validation or authorization."""
        return False

    async def _send_overloaded_response(
        self, seq_id: int, *, limit: int = MAX_INFLIGHT_ACTIONS
    ) -> None:
        response = ActionResponse.error(
            f"Runtime connection is busy (max {limit} concurrent actions)"
        )
        response.seq_id = seq_id
        with contextlib.suppress(ConnectionClosedError):
            await self._send_message(response)

    def _action_task_done(self, task: asyncio.Task[None]) -> None:
        self._action_tasks.discard(task)
        self._reserved_action_tasks.discard(task)
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
        self._reserved_action_tasks.clear()
        self._active_tasks.clear()

    def cancel_inflight_messages(self) -> None:
        """Cancel peer requests already accepted by this handler."""

        for action_task in tuple(self._action_tasks):
            action_task.cancel()

    def cancel_inflight_messages_for_context(
        self,
        action_context: ActionEnvelopeContext,
    ) -> None:
        """Cancel only requests owned by one exact installation revision."""

        for action_task, owned_context in tuple(self._action_task_contexts.items()):
            if owned_context == action_context:
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
                raise ActionCallError(f"{response.message}", response.data)
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
                        raise ActionCallError(f"{response.message}", response.data)

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
            return self._current_action_context.get() or self._bound_action_context

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

    def resolve_effective_action_context(
        self,
        action_context: ActionEnvelopeContext | dict[str, Any] | None = None,
    ) -> ActionEnvelopeContext | None:
        """Resolve explicit, task-local, then connection-bound authority."""

        if action_context is not None:
            return self.resolve_outbound_action_context(action_context)
        return self._current_action_context.get() or self._bound_action_context

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
    def _transfer_race_hook(self, event: str, **details: Any) -> None:
        """Deterministic no-op hook used by filesystem race regression tests."""

        del event, details

    def _require_transfer_root(self) -> int:
        if self._file_storage_root_fd_closed:
            raise ValueError("Invalid file transfer root")
        try:
            path_stat = os.stat(self.file_storage_dir, follow_symlinks=False)
        except OSError:
            raise ValueError("Invalid file transfer root") from None
        if (
            not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != self._file_storage_root_identity
        ):
            raise ValueError("Invalid file transfer root")
        self._transfer_race_hook("after_root_validation")
        return self._file_storage_root_fd

    def _bound_transfer_root(self) -> int:
        if self._file_storage_root_fd_closed:
            raise ValueError("Invalid file transfer root")
        return self._file_storage_root_fd

    def _close_transfer_root_if_clean(self) -> None:
        if self._file_storage_root_fd_closed or self._owned_transfer_files:
            return
        os.close(self._file_storage_root_fd)
        self._file_storage_root_fd_closed = True

    def _read_regular(
        self,
        directory_name: str,
        file_name: str,
        *,
        private: bool = False,
        max_bytes: int | None = None,
    ) -> tuple[bytes, os.stat_result]:
        return _read_regular_at(
            self._require_transfer_root(),
            directory_name,
            file_name,
            private=private,
            max_bytes=max_bytes,
        )

    def _read_regular_bound(
        self,
        directory_name: str,
        file_name: str,
        *,
        private: bool = False,
        max_bytes: int | None = None,
    ) -> tuple[bytes, os.stat_result]:
        return _read_regular_at(
            self._bound_transfer_root(),
            directory_name,
            file_name,
            private=private,
            max_bytes=max_bytes,
        )

    def _quarantine_expected_regular(
        self,
        directory_name: str,
        file_name: str,
        expected_stat: os.stat_result,
        *,
        role: str,
        expected_bytes: bytes | None = None,
        missing_ok: bool,
    ) -> bool:
        root_fd = self._bound_transfer_root()
        try:
            directory_fd = _open_transfer_directory(
                root_fd, directory_name, create=False
            )
        except FileNotFoundError:
            if missing_ok:
                return False
            raise
        quarantine_name = f".quarantine-{uuid.uuid4().hex}"
        try:
            self._transfer_race_hook(
                "before_quarantine_rename",
                role=role,
                directory_name=directory_name,
                file_name=file_name,
            )
            try:
                os.rename(
                    file_name,
                    quarantine_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            except FileNotFoundError:
                if missing_ok:
                    return False
                raise

            verified = False
            try:
                descriptor = os.open(
                    quarantine_name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                try:
                    quarantined_stat = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(quarantined_stat.st_mode)
                        or quarantined_stat.st_dev != expected_stat.st_dev
                        or quarantined_stat.st_ino != expected_stat.st_ino
                    ):
                        raise ValueError("Invalid file transfer capability")
                    if expected_bytes is not None:
                        with os.fdopen(descriptor, "rb", closefd=False) as file:
                            if file.read(len(expected_bytes) + 1) != expected_bytes:
                                raise ValueError("Invalid file transfer capability")
                    verified = True
                finally:
                    os.close(descriptor)
                os.remove(quarantine_name, dir_fd=directory_fd)
                return True
            except BaseException:
                # Never restore or remove a name that resolved to a mismatching
                # inode. Retaining it and the owner record makes retries fail
                # closed instead of deleting a same-UID mutator's replacement.
                if verified:
                    with contextlib.suppress(OSError):
                        os.link(
                            quarantine_name,
                            file_name,
                            src_dir_fd=directory_fd,
                            dst_dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                    with contextlib.suppress(OSError):
                        os.remove(quarantine_name, dir_fd=directory_fd)
                raise
        finally:
            os.close(directory_fd)

    @classmethod
    def _serialize_transfer_record(
        cls,
        transfer_context: ActionEnvelopeContext | None,
        claim_id: str,
        payload_identity: tuple[int, int],
    ) -> bytes:
        return json.dumps(
            {
                "claim_id": claim_id,
                "payload_dev": payload_identity[0],
                "payload_ino": payload_identity[1],
                "owner": None
                if transfer_context is None
                else transfer_context.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _parse_transfer_record(
        raw_owner: bytes,
    ) -> tuple[ActionEnvelopeContext | None, str | None, tuple[int, int] | None]:
        stored_data = json.loads(raw_owner)
        if (
            isinstance(stored_data, dict)
            and set(stored_data) == {"claim_id", "owner", "payload_dev", "payload_ino"}
            and isinstance(stored_data["claim_id"], str)
            and stored_data["claim_id"]
            and isinstance(stored_data["payload_dev"], int)
            and isinstance(stored_data["payload_ino"], int)
        ):
            owner_data = stored_data["owner"]
            return (
                None
                if owner_data is None
                else parse_action_envelope_context(owner_data),
                stored_data["claim_id"],
                (stored_data["payload_dev"], stored_data["payload_ino"]),
            )
        if (
            isinstance(stored_data, dict)
            and set(stored_data) == {"claim_id", "owner"}
            and isinstance(stored_data["claim_id"], str)
            and stored_data["claim_id"]
        ):
            owner_data = stored_data["owner"]
            return (
                None
                if owner_data is None
                else parse_action_envelope_context(owner_data),
                stored_data["claim_id"],
                None,
            )
        return (
            None if stored_data is None else parse_action_envelope_context(stored_data),
            None,
            None,
        )

    @staticmethod
    def _context_can_access_transfer(
        effective_context: ActionEnvelopeContext | None,
        stored_context: ActionEnvelopeContext | None,
    ) -> bool:
        return (
            effective_context is None
            or effective_context == stored_context
            or (
                isinstance(stored_context, InstallationBinding)
                and not isinstance(effective_context, InstallationBinding)
                and stored_context.model_dump(
                    exclude={"runtime_revision", "artifact_digest"}
                )
                == effective_context.model_dump()
            )
        )

    def _read_private_file(self, path: str) -> tuple[bytes, os.stat_result]:
        return self._read_regular(
            os.path.basename(os.path.dirname(path)),
            os.path.basename(path),
            private=True,
        )

    def _read_private_file_bound(self, path: str) -> tuple[bytes, os.stat_result]:
        return self._read_regular_bound(
            os.path.basename(os.path.dirname(path)),
            os.path.basename(path),
            private=True,
        )

    def _create_transfer_stage(
        self,
        file_key: str,
        transfer_context: ActionEnvelopeContext | None,
        chunk_amount: int,
    ) -> _TransferStage:
        namespace = _transfer_namespace(transfer_context)
        namespace_fd = _open_transfer_directory(
            self._bound_transfer_root(), namespace, create=True
        )
        temp_name = f".payload-{uuid.uuid4().hex}.tmp"
        try:
            record_name = _transfer_owner_record_name(file_key)
            if record_name is not None:
                try:
                    owner_dir_fd = _open_transfer_directory(
                        self._bound_transfer_root(), _TRANSFER_OWNER_DIR, create=False
                    )
                except FileNotFoundError:
                    owner_dir_fd = None
                if owner_dir_fd is not None:
                    try:
                        try:
                            owner_fd = os.open(
                                record_name,
                                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                                dir_fd=owner_dir_fd,
                            )
                        except FileNotFoundError:
                            owner_fd = None
                        except OSError:
                            raise ValueError(
                                "Invalid file transfer capability"
                            ) from None
                        if owner_fd is not None:
                            os.close(owner_fd)
                            raise ValueError("Invalid file transfer capability")
                    finally:
                        os.close(owner_dir_fd)
            # Published names are immutable.  Opening them for write (especially
            # with O_TRUNC) would let a raced replacement be modified.
            try:
                existing_fd = os.open(
                    file_key,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=namespace_fd,
                )
            except FileNotFoundError:
                existing_fd = None
            except OSError:
                raise ValueError("Invalid file transfer capability") from None
            if existing_fd is not None:
                os.close(existing_fd)
                raise ValueError("Invalid file transfer capability")
            descriptor = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=namespace_fd,
            )
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                os.close(descriptor)
                raise ValueError("Invalid file transfer capability")
            return _TransferStage(
                namespace=namespace,
                temp_name=temp_name,
                descriptor=descriptor,
                file_stat=file_stat,
                transfer_context=transfer_context,
                claim_id=(
                    uuid.uuid4().hex
                    if _transfer_owner_record_name(file_key) is not None
                    else None
                ),
                chunk_amount=chunk_amount,
            )
        except OSError:
            raise ValueError("Invalid file transfer capability") from None
        finally:
            os.close(namespace_fd)

    def _discard_transfer_stage(self, file_key: str, stage: _TransferStage) -> None:
        with contextlib.suppress(OSError):
            os.close(stage.descriptor)
        try:
            namespace_fd = _open_transfer_directory(
                self._bound_transfer_root(), stage.namespace, create=False
            )
        except (FileNotFoundError, ValueError):
            namespace_fd = None
        if namespace_fd is not None:
            try:
                with contextlib.suppress(OSError):
                    os.remove(stage.temp_name, dir_fd=namespace_fd)
            finally:
                os.close(namespace_fd)
        self._transfer_stages.pop(file_key, None)

    def _publish_owner_record(
        self,
        file_key: str,
        stage: _TransferStage,
        file_path: str,
    ) -> None:
        record_name = _transfer_owner_record_name(file_key)
        if record_name is None or stage.claim_id is None:
            return
        owner_dir_fd = _open_transfer_directory(
            self._bound_transfer_root(), _TRANSFER_OWNER_DIR, create=True
        )
        temp_name = f".owner-{uuid.uuid4().hex}.tmp"
        serialized = self._serialize_transfer_record(
            stage.transfer_context,
            stage.claim_id,
            (stage.file_stat.st_dev, stage.file_stat.st_ino),
        )
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=owner_dir_fd,
            )
            os.write(descriptor, serialized)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            self._transfer_race_hook(
                "before_owner_link", file_key=file_key, record_name=record_name
            )
            os.link(
                temp_name,
                record_name,
                src_dir_fd=owner_dir_fd,
                dst_dir_fd=owner_dir_fd,
                follow_symlinks=False,
            )
            stage.owner_published = True
            owner_path = os.path.join(
                self.file_storage_dir, _TRANSFER_OWNER_DIR, record_name
            )
            # Track before durability can fail: close can now clean the exact
            # payload/owner pair instead of silently orphaning a sidecar.
            self._owned_transfer_files.add(file_path)
            self._owned_transfer_records.add(owner_path)
            self._owned_transfer_contexts[file_path] = stage.transfer_context
            self._owned_transfer_claims[file_path] = stage.claim_id
            self._owned_transfer_identities[file_path] = (
                stage.file_stat.st_dev,
                stage.file_stat.st_ino,
            )
            os.fsync(owner_dir_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            with contextlib.suppress(OSError):
                os.remove(temp_name, dir_fd=owner_dir_fd)
            os.close(owner_dir_fd)

    def _write_file_chunk(
        self,
        file_key: str,
        transfer_context: ActionEnvelopeContext | None,
        chunk_bytes: bytes,
        chunk_index: int,
        chunk_amount: int,
    ) -> None:
        root = self.file_storage_dir
        file_path = os.path.join(root, _transfer_namespace(transfer_context), file_key)
        self._require_transfer_root()

        with _locked_transfer(root, file_key) as lock_key:
            active = _active_transfer_handler(lock_key)
            if active is not None and active is not self:
                raise ValueError("Invalid file transfer capability")
            stage = self._transfer_stages.get(file_key)
            if chunk_index == 0:
                if stage is not None or file_path in self._owned_transfer_files:
                    raise ValueError("Invalid file transfer capability")
                if (
                    len(self._owned_transfer_files) + len(self._transfer_stages)
                    >= MAX_ACTIVE_FILE_TRANSFERS
                ):
                    raise ValueError("Active file transfer capacity reached")
                if (
                    self.max_file_bytes is not None
                    and len(chunk_bytes) > self.max_file_bytes
                ):
                    raise ValueError("File transfer exceeds the configured size limit")
                stage = self._create_transfer_stage(
                    file_key, transfer_context, chunk_amount
                )
                self._transfer_stages[file_key] = stage
                _set_active_transfer_handler(lock_key, self)
            elif stage is None:
                raise ValueError("Invalid file transfer capability")

            assert stage is not None
            if (
                stage.transfer_context != transfer_context
                or stage.chunk_amount != chunk_amount
                or stage.next_index != chunk_index
            ):
                raise ValueError("Invalid file transfer capability")
            resulting_size = stage.size + len(chunk_bytes)
            if self.max_file_bytes is not None and resulting_size > self.max_file_bytes:
                self._discard_transfer_stage(file_key, stage)
                _clear_active_transfer_handler(lock_key, self)
                raise ValueError("File transfer exceeds the configured size limit")

            try:
                self._transfer_race_hook(
                    "before_staging_write", file_key=file_key, namespace=stage.namespace
                )
                current_stat = os.fstat(stage.descriptor)
                if (
                    current_stat.st_dev != stage.file_stat.st_dev
                    or current_stat.st_ino != stage.file_stat.st_ino
                ):
                    raise ValueError("Invalid file transfer capability")
                written = os.write(stage.descriptor, chunk_bytes)
                if written != len(chunk_bytes):
                    raise OSError("short file transfer write")
                stage.size = resulting_size
                stage.next_index += 1
                if chunk_index + 1 != chunk_amount:
                    return

                os.fsync(stage.descriptor)
                namespace_fd = _open_transfer_directory(
                    self._bound_transfer_root(), stage.namespace, create=False
                )
                try:
                    try:
                        os.link(
                            stage.temp_name,
                            file_key,
                            src_dir_fd=namespace_fd,
                            dst_dir_fd=namespace_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        raise ValueError("Invalid file transfer capability") from None
                    stage.payload_published = True
                    os.fsync(namespace_fd)
                finally:
                    os.close(namespace_fd)

                if stage.claim_id is not None:
                    self._publish_owner_record(file_key, stage, file_path)
                else:
                    self._owned_transfer_files.add(file_path)
                    self._owned_transfer_contexts[file_path] = transfer_context
                    self._owned_transfer_claims[file_path] = None
                    self._owned_transfer_identities[file_path] = (
                        stage.file_stat.st_dev,
                        stage.file_stat.st_ino,
                    )
                self._discard_transfer_stage(file_key, stage)
            except BaseException:
                if stage.owner_published:
                    # Publication happened; keep all authority tracked for a
                    # truthful close/delete retry.
                    self._discard_transfer_stage(file_key, stage)
                else:
                    if stage.payload_published:
                        try:
                            self._quarantine_expected_regular(
                                stage.namespace,
                                file_key,
                                stage.file_stat,
                                role="payload",
                                missing_ok=False,
                            )
                        except (OSError, ValueError, FileNotFoundError):
                            # A raced replacement is not ours to delete.
                            pass
                    self._discard_transfer_stage(file_key, stage)
                    _clear_active_transfer_handler(lock_key, self)
                raise

    async def _resolve_transfer_context(
        self,
        file_key: str,
        action_context: ActionEnvelopeContext | dict[str, Any] | None,
    ) -> tuple[ActionEnvelopeContext | None, tuple[int, int] | None]:
        file_key = _validate_file_key(file_key)
        effective_context = self.resolve_effective_action_context(action_context)
        record_path = _transfer_owner_record_path(file_key, self.file_storage_dir)
        if record_path is None:
            return effective_context, None
        try:
            raw_owner, _owner_stat = await _run_small_protocol_work(
                self._read_private_file, record_path
            )
            stored_context, _claim_id, expected_payload = self._parse_transfer_record(
                raw_owner
            )
        except FileNotFoundError:
            raise FileNotFoundError(file_key) from None
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("Invalid file transfer capability") from None
        if not self._context_can_access_transfer(
            effective_context,
            stored_context,
        ):
            raise FileNotFoundError(file_key)
        return stored_context, expected_payload

    async def send_file(
        self,
        file_bytes: bytes,
        file_extension: str,
        *,
        action_context: ActionEnvelopeContext | dict[str, Any] | None = None,
    ) -> str:
        """Send a file to the peer, chunk by chunk, in base64."""
        if self.max_file_bytes is not None and len(file_bytes) > self.max_file_bytes:
            raise ValueError("File transfer exceeds the configured size limit")
        if not isinstance(file_extension, str):
            raise ValueError("Invalid file transfer extension")
        extension = file_extension.strip(".")
        if extension and _SAFE_FILE_EXTENSION_PATTERN.fullmatch(extension) is None:
            raise ValueError("Invalid file transfer extension")
        suffix = f".{extension}" if extension else ""
        file_key = f"ft1_{uuid.uuid4().hex}{uuid.uuid4().hex}{suffix}"
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
                action_context=action_context,
            )
        return file_key

    async def read_local_file(
        self,
        file_key: str,
        *,
        action_context: ActionEnvelopeContext | dict[str, Any] | None = None,
    ) -> bytes:
        transfer_context, expected_payload = await self._resolve_transfer_context(
            file_key, action_context
        )

        def read_file() -> bytes:
            with _locked_transfer(self.file_storage_dir, file_key):
                content, file_stat = self._read_regular(
                    _transfer_namespace(transfer_context),
                    file_key,
                    max_bytes=self.max_file_bytes,
                )
                if (
                    expected_payload is not None
                    and (
                        file_stat.st_dev,
                        file_stat.st_ino,
                    )
                    != expected_payload
                ):
                    raise ValueError("Invalid file transfer capability")
                return content

        content = await run_blocking_with_backpressure(read_file)
        if self.max_file_bytes is not None and len(content) > self.max_file_bytes:
            raise ValueError("File transfer exceeds the configured size limit")
        return content

    async def delete_local_file(
        self,
        file_key: str,
        *,
        action_context: ActionEnvelopeContext | dict[str, Any] | None = None,
    ) -> None:
        file_key = _validate_file_key(file_key)
        effective_context = self.resolve_effective_action_context(action_context)
        async with self._file_transfer_lock:
            await run_blocking_with_backpressure(
                self._delete_transfer_sync,
                file_key,
                effective_context,
                False,
            )

    def _delete_transfer_sync(
        self,
        file_key: str,
        transfer_context: ActionEnvelopeContext | None,
        cleanup: bool,
    ) -> bool:
        if not cleanup:
            self._require_transfer_root()
        owner_record = _transfer_owner_record_path(file_key, self.file_storage_dir)
        with _locked_transfer(self.file_storage_dir, file_key) as lock_key:
            stored_context, current_claim_id, expected_payload_identity = (
                transfer_context,
                None,
                None,
            )
            owner_stat: os.stat_result | None = None
            raw_owner: bytes | None = None
            if owner_record is not None:
                try:
                    raw_owner, owner_stat = self._read_private_file_bound(owner_record)
                    (
                        stored_context,
                        current_claim_id,
                        expected_payload_identity,
                    ) = self._parse_transfer_record(raw_owner)
                except FileNotFoundError:
                    return False
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    raise ValueError("Invalid file transfer capability") from None
                if not self._context_can_access_transfer(
                    transfer_context,
                    stored_context,
                ):
                    return False

            namespace = _transfer_namespace(stored_context)
            file_path = os.path.join(self.file_storage_dir, namespace, file_key)
            if cleanup:
                expected_claim_id = self._owned_transfer_claims.get(file_path)
                if current_claim_id != expected_claim_id:
                    self._owned_transfer_files.discard(file_path)
                    self._owned_transfer_contexts.pop(file_path, None)
                    self._owned_transfer_claims.pop(file_path, None)
                    if owner_record is not None:
                        self._owned_transfer_records.discard(owner_record)
                    return False
                active = _active_transfer_handler(lock_key)
                if active is not None and active is not self:
                    self._owned_transfer_files.discard(file_path)
                    self._owned_transfer_contexts.pop(file_path, None)
                    self._owned_transfer_claims.pop(file_path, None)
                    if owner_record is not None:
                        self._owned_transfer_records.discard(owner_record)
                    return False
            try:
                _payload_bytes, payload_stat = self._read_regular_bound(
                    namespace,
                    file_key,
                )
            except FileNotFoundError:
                payload_stat = None
            if expected_payload_identity is not None:
                if payload_stat is None:
                    if file_path not in self._deleted_transfer_payloads:
                        # Durable owner authority outlives an externally missing
                        # or moved payload; this is corruption, not success.
                        raise ValueError("Invalid file transfer capability")
                elif (
                    payload_stat.st_dev,
                    payload_stat.st_ino,
                ) != expected_payload_identity:
                    raise ValueError("Invalid file transfer capability")
            try:
                if payload_stat is not None:
                    payload_removed = self._quarantine_expected_regular(
                        namespace,
                        file_key,
                        payload_stat,
                        role="payload",
                        missing_ok=False,
                    )
                    if payload_removed:
                        self._deleted_transfer_payloads.add(file_path)
            except (OSError, ValueError):
                if cleanup:
                    return False
                raise
            was_active = _is_active_transfer_handler(lock_key, self)

            if owner_record is not None:
                assert owner_stat is not None and raw_owner is not None
                try:
                    self._quarantine_expected_regular(
                        _TRANSFER_OWNER_DIR,
                        os.path.basename(owner_record),
                        owner_stat,
                        role="owner",
                        expected_bytes=raw_owner,
                        missing_ok=False,
                    )
                except (OSError, ValueError):
                    if cleanup:
                        return False
                    raise
                self._owned_transfer_records.discard(owner_record)
            self._owned_transfer_files.discard(file_path)
            self._owned_transfer_contexts.pop(file_path, None)
            self._owned_transfer_claims.pop(file_path, None)
            self._owned_transfer_identities.pop(file_path, None)
            self._deleted_transfer_payloads.discard(file_path)
            if not cleanup or was_active:
                _set_active_transfer_handler(lock_key, None)
            return True

    async def _cleanup_owned_transfers(self) -> None:
        async with self._file_transfer_lock:
            file_paths = tuple(self._owned_transfer_files)
            for file_path in file_paths:
                try:
                    await run_blocking_cleanup(
                        self._delete_transfer_sync,
                        os.path.basename(file_path),
                        self._owned_transfer_contexts[file_path],
                        True,
                    )
                except OSError as exc:
                    with _locked_transfer(
                        self.file_storage_dir, os.path.basename(file_path)
                    ) as lock_key:
                        _clear_active_transfer_handler(lock_key, self)
                    logger.warning(
                        "Failed to clean runtime transfer file %s: %s",
                        os.path.basename(file_path),
                        exc,
                    )
