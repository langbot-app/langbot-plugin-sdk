"""Dify Service API client for Runner.

This module provides a minimal Dify API client that doesn't depend on LangBot internals.
"""

from __future__ import annotations

import json
import logging
import typing

import httpx

logger = logging.getLogger(__name__)


class DifyAPIError(Exception):
    """Dify API error."""

    def __init__(self, message: str, code: str = "dify.api_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class DifyConfigError(Exception):
    """Dify configuration error."""

    def __init__(self, message: str, code: str = "dify.config_invalid"):
        self.message = message
        self.code = code
        super().__init__(message)


class AsyncDifyClient:
    """Minimal Dify Service API client for Runner.

    Supports:
    - chat-messages (for chat and agent app types)
    - workflows/run (for workflow app type)
    - file upload (for multimodal input)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.dify.ai/v1",
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def chat_messages(
        self,
        inputs: dict[str, typing.Any],
        query: str,
        user: str,
        conversation_id: str = "",
        files: list[dict[str, typing.Any]] = None,
    ) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
        """Send chat message with streaming response.

        Yields SSE events as dicts.
        """
        files = files or []

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            trust_env=True,
        ) as client:
            payload = {
                "inputs": inputs,
                "query": query,
                "user": user,
                "response_mode": "streaming",
                "conversation_id": conversation_id,
                "files": files,
            }

            try:
                async with client.stream(
                    "POST",
                    "/chat-messages",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        error_text = error_body.decode("utf-8", errors="replace")
                        raise DifyAPIError(
                            f"Dify API error: {response.status_code} - {error_text[:200]}",
                            code="dify.http_error",
                        )

                    async for line in response.aiter_lines():
                        if not line or not line.strip():
                            continue
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str:
                                try:
                                    yield json.loads(data_str)
                                except json.JSONDecodeError as e:
                                    logger.warning(f"Failed to parse Dify SSE data: {e}")
                                    raise DifyAPIError(
                                        f"Invalid Dify response format: {data_str[:100]}",
                                        code="dify.response_invalid",
                                    ) from None
            except httpx.TimeoutException:
                raise DifyAPIError(
                    f"Dify API request timed out after {self.timeout}s",
                    code="dify.timeout",
                ) from None
            except httpx.HTTPStatusError as e:
                raise DifyAPIError(
                    f"Dify HTTP error: {e.response.status_code}",
                    code="dify.http_error",
                ) from None

    async def workflow_run(
        self,
        inputs: dict[str, typing.Any],
        user: str,
        files: list[dict[str, typing.Any]] = None,
    ) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
        """Run workflow with streaming response.

        Yields SSE events as dicts.
        """
        files = files or []

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            trust_env=True,
        ) as client:
            payload = {
                "inputs": inputs,
                "user": user,
                "response_mode": "streaming",
                "files": files,
            }

            try:
                async with client.stream(
                    "POST",
                    "/workflows/run",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        error_text = error_body.decode("utf-8", errors="replace")
                        raise DifyAPIError(
                            f"Dify API error: {response.status_code} - {error_text[:200]}",
                            code="dify.http_error",
                        )

                    async for line in response.aiter_lines():
                        if not line or not line.strip():
                            continue
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str:
                                try:
                                    yield json.loads(data_str)
                                except json.JSONDecodeError as e:
                                    logger.warning(f"Failed to parse Dify SSE data: {e}")
                                    raise DifyAPIError(
                                        f"Invalid Dify response format: {data_str[:100]}",
                                        code="dify.response_invalid",
                                    ) from None
            except httpx.TimeoutException:
                raise DifyAPIError(
                    f"Dify API request timed out after {self.timeout}s",
                    code="dify.timeout",
                ) from None
            except httpx.HTTPStatusError as e:
                raise DifyAPIError(
                    f"Dify HTTP error: {e.response.status_code}",
                    code="dify.http_error",
                ) from None

    async def workflow_submit(
        self,
        form_token: str,
        workflow_run_id: str,
        inputs: dict[str, typing.Any],
        user: str,
        action: str = "",
    ) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
        """Submit human input and stream the resumed workflow events."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                trust_env=True,
            ) as client:
                response = await client.post(
                    f"/form/human_input/{form_token}",
                    headers=headers,
                    json={"inputs": inputs, "user": user, "action": action},
                )
                if not response.is_success:
                    raise DifyAPIError(
                        f"Dify API error: {response.status_code} - {response.text[:200]}",
                        code="dify.http_error",
                    )

                async with client.stream(
                    "GET",
                    f"/workflow/{workflow_run_id}/events",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    params={"user": user},
                ) as event_response:
                    if not event_response.is_success:
                        body = await event_response.aread()
                        raise DifyAPIError(
                            f"Dify API error: {event_response.status_code} - "
                            f"{body.decode('utf-8', errors='replace')[:200]}",
                            code="dify.http_error",
                        )
                    async for line in event_response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            yield json.loads(data_str)
                        except json.JSONDecodeError:
                            raise DifyAPIError(
                                f"Invalid Dify response format: {data_str[:100]}",
                                code="dify.response_invalid",
                            ) from None
        except httpx.TimeoutException:
            raise DifyAPIError(
                f"Dify API request timed out after {self.timeout}s",
                code="dify.timeout",
            ) from None

    async def upload_file(
        self,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
        user: str,
    ) -> dict[str, typing.Any]:
        """Upload file to Dify and return file info with id."""
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            trust_env=True,
        ) as client:
            files = {"file": (file_name, file_bytes, content_type)}
            data = {"user": user}

            try:
                response = await client.post(
                    "/files/upload",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=files,
                    data=data,
                )

                if response.status_code != 201:
                    error_text = response.text[:200]
                    raise DifyAPIError(
                        f"Dify file upload failed: {response.status_code} - {error_text}",
                        code="dify.http_error",
                    )

                return response.json()
            except httpx.TimeoutException:
                raise DifyAPIError(
                    f"Dify file upload timed out after {self.timeout}s",
                    code="dify.timeout",
                ) from None


def extract_text_from_output(value: typing.Any) -> str:
    """Extract text content from Dify output payload."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        # Try to parse as JSON to extract content field
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and isinstance(parsed.get("content"), str):
                return parsed["content"]
        except json.JSONDecodeError:
            pass
        return value
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, str):
            return content
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def process_thinking_content(content: str, remove_think: bool = False) -> tuple[str, str]:
    """Process thinking content (reasoning tags) in Dify responses.

    Args:
        content: Original content
        remove_think: Whether to remove thinking tags

    Returns:
        (processed_content, thinking_content)
    """
    import re

    thinking_content = ""
    if content and "<think>" in content and "</think>" in content:
        think_pattern = r"<think>(.*?)</think>"
        think_matches = re.findall(think_pattern, content, re.DOTALL)
        if think_matches:
            thinking_content = "\n".join(think_matches)
            content = re.sub(think_pattern, "", content, flags=re.DOTALL).strip()

    if remove_think:
        return content, ""
    else:
        if thinking_content:
            content = f"<think>\n{thinking_content}\n</think>\n{content}".strip()
        return content, thinking_content
