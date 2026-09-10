"""Tbox API client wrapper for Runner.

This module provides an async wrapper around tboxsdk for use with the Runner plugin.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import tempfile
import threading
import typing

logger = logging.getLogger(__name__)


class TboxAPIError(Exception):
    """Tbox API error."""

    def __init__(self, message: str, code: str = "tbox.api_error", retryable: bool = False):
        self.message = message
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class TboxConfigError(Exception):
    """Tbox configuration error."""

    def __init__(self, message: str, code: str = "tbox.config_invalid"):
        self.message = message
        self.code = code
        super().__init__(message)


class AsyncTboxClient:
    """Async wrapper for tboxsdk.TboxClient.

    Provides async methods for:
    - chat: Send messages to Tbox app (streaming or non-streaming)
    - upload_file: Upload files (images) to Tbox

    The underlying tboxsdk is synchronous, so we run blocking calls in a thread pool.
    """

    def __init__(self, api_key: str, timeout: float = 120.0):
        """Initialize the Tbox client.

        Args:
            api_key: Tbox authorization token
        """
        self.api_key = api_key
        self.timeout = timeout
        self._sync_client = None

    def _get_client(self):
        """Lazily initialize the sync TboxClient."""
        if self._sync_client is None:
            from tboxsdk.tbox import TboxClient

            self._sync_client = TboxClient(authorization=self.api_key)
        return self._sync_client

    async def upload_file(self, file_bytes: bytes, file_name: str) -> str:
        """Upload a file to Tbox.

        Args:
            file_bytes: File content as bytes
            file_name: Name of the file (used to determine extension)

        Returns:
            Tbox file ID

        Raises:
            TboxAPIError: If upload fails
        """
        import os

        # Tbox SDK requires a file path, so we write to a temp file
        loop = asyncio.get_running_loop()

        def _upload_sync():
            client = self._get_client()
            # Create temp file with proper extension
            ext = os.path.splitext(file_name)[1] or ".bin"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            try:
                result = client.upload_file(tmp_path)
                return result.get("data", "")
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        try:
            file_id = await asyncio.wait_for(loop.run_in_executor(None, _upload_sync), timeout=self.timeout)
            return file_id
        except TimeoutError:
            raise TboxAPIError(
                f"Tbox file upload timed out after {self.timeout}s",
                code="tbox.timeout",
                retryable=True,
            ) from None
        except Exception as e:
            if _is_timeout_error(e):
                raise TboxAPIError(
                    f"Tbox file upload timed out after {self.timeout}s",
                    code="tbox.timeout",
                    retryable=True,
                ) from None
            raise TboxAPIError(f"Tbox file upload failed: {e}", code="tbox.upload_error") from e

    async def chat(
        self,
        app_id: str,
        user_id: str,
        query: str,
        stream: bool = True,
        conversation_id: str | None = None,
        files: list[dict[str, typing.Any]] | None = None,
    ) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
        """Send a chat message to Tbox.

        Args:
            app_id: Tbox application ID
            user_id: User identifier
            query: Text message content
            stream: Whether to stream the response
            conversation_id: Existing conversation ID (for stateful sessions)
            files: List of file dicts with file_id and type

        Yields:
            For streaming: chunks with type 'chunk', 'thinking', or 'error'
            For non-streaming: single chunk with full response

        Raises:
            TboxAPIError: If chat request fails
        """
        from tboxsdk.model.file import File, FileType

        # Convert file dicts to Tbox File objects
        tbox_files = None
        if files:
            tbox_files = []
            for f in files:
                file_type = FileType.IMAGE if f.get("type") == "image" else FileType.IMAGE
                tbox_files.append(File(file_id=f["file_id"], type=file_type))

        def _chat_sync():
            client = self._get_client()
            return client.chat(
                app_id=app_id,
                user_id=user_id,
                query=query,
                stream=stream,
                conversation_id=conversation_id,
                files=tbox_files,
            )

        try:
            if stream:
                async for chunk in _iterate_sync_in_thread(_chat_sync, timeout=self.timeout):
                    yield chunk
            else:
                response = await asyncio.wait_for(
                    asyncio.to_thread(_chat_sync),
                    timeout=self.timeout,
                )
                yield response

        except TimeoutError:
            raise TboxAPIError(
                f"Tbox chat request timed out after {self.timeout}s",
                code="tbox.timeout",
                retryable=True,
            ) from None
        except Exception as e:
            if _is_timeout_error(e):
                raise TboxAPIError(
                    f"Tbox chat request timed out after {self.timeout}s",
                    code="tbox.timeout",
                    retryable=True,
                ) from None
            raise TboxAPIError(f"Tbox chat request failed: {e}", code="tbox.chat_error") from e


def _is_timeout_error(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in exc.__class__.__name__.lower()


async def _iterate_sync_in_thread(
    factory: typing.Callable[[], typing.Iterable[dict[str, typing.Any]]],
    *,
    timeout: float,
) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
    """Iterate a blocking provider stream without blocking the event loop."""
    sentinel = object()
    output: queue.Queue[typing.Any] = queue.Queue()

    def _worker() -> None:
        try:
            for item in factory():
                output.put(item)
        except BaseException as exc:
            output.put(exc)
        finally:
            output.put(sentinel)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    while True:
        item = await asyncio.wait_for(asyncio.to_thread(output.get), timeout=timeout)
        if item is sentinel:
            break
        if isinstance(item, BaseException):
            raise item
        yield item
