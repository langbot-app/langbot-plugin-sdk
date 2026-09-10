"""n8n Webhook client for Runner.

This module provides a minimal n8n webhook client that doesn't depend on LangBot internals.
"""

from __future__ import annotations

import json
import logging
import time
import typing

import httpx

logger = logging.getLogger(__name__)


class N8nAPIError(Exception):
    """n8n API error."""

    def __init__(self, message: str, code: str = "n8n.api_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class N8nConfigError(Exception):
    """n8n configuration error."""

    def __init__(self, message: str, code: str = "n8n.config_invalid"):
        self.message = message
        self.code = code
        super().__init__(message)


class AsyncN8nClient:
    """Minimal n8n Webhook client for Runner.

    Supports:
    - Webhook calls with various authentication types
    - Streaming response (type: item/end format)
    - Non-streaming JSON response
    """

    def __init__(
        self,
        webhook_url: str,
        timeout: float = 120.0,
        output_key: str = "response",
    ):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.output_key = output_key

    async def call_webhook(
        self,
        payload: dict[str, typing.Any],
        auth_type: str = "none",
        auth_config: dict[str, typing.Any] = None,
    ) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
        """Call n8n webhook with authentication.

        Yields response events as dicts with:
        - type: "item" for content chunks, "end" for completion, "json" for non-streaming
        - content: text content for "item" type
        - data: full response data for "json" type
        """
        auth_config = auth_config or {}

        async with httpx.AsyncClient(
            timeout=self.timeout,
            trust_env=True,
        ) as client:
            headers = self._build_headers(auth_type, auth_config)
            auth = self._build_auth(auth_type, auth_config)

            try:
                async with client.stream(
                    "POST",
                    self.webhook_url,
                    json=payload,
                    headers=headers,
                    auth=auth,
                ) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        error_text = error_body.decode("utf-8", errors="replace")
                        raise N8nAPIError(
                            f"n8n webhook error: {response.status_code} - {error_text[:200]}",
                            code="n8n.http_error",
                        )

                    async for event in self._parse_response(response):
                        yield event

            except httpx.TimeoutException:
                raise N8nAPIError(
                    f"n8n webhook request timed out after {self.timeout}s",
                    code="n8n.timeout",
                ) from None
            except httpx.HTTPStatusError as e:
                raise N8nAPIError(
                    f"n8n HTTP error: {e.response.status_code}",
                    code="n8n.http_error",
                ) from None

    def _build_headers(
        self,
        auth_type: str,
        auth_config: dict[str, typing.Any],
    ) -> dict[str, str]:
        """Build request headers based on auth type."""
        headers = {"Content-Type": "application/json"}

        if auth_type == "jwt":
            import jwt

            secret = auth_config.get("jwt_secret", "")
            algorithm = auth_config.get("jwt_algorithm", "HS256")

            jwt_payload = {
                "exp": int(time.time()) + 3600,  # 1 hour expiry
                "iat": int(time.time()),
                "sub": "n8n-webhook",
            }
            token = jwt.encode(jwt_payload, secret, algorithm=algorithm)
            headers["Authorization"] = f"Bearer {token}"
            logger.debug("Using JWT authentication")

        elif auth_type == "header":
            header_name = auth_config.get("header_name", "")
            header_value = auth_config.get("header_value", "")
            if header_name and header_value:
                headers[header_name] = header_value
                logger.debug(f"Using header authentication: {header_name}")

        return headers

    def _build_auth(
        self,
        auth_type: str,
        auth_config: dict[str, typing.Any],
    ) -> httpx.Auth | None:
        """Build httpx auth object for basic auth."""
        if auth_type == "basic":
            username = auth_config.get("basic_username", "")
            password = auth_config.get("basic_password", "")
            logger.debug(f"Using basic authentication: {username}")
            return httpx.BasicAuth(username, password)
        return None

    async def _parse_response(
        self,
        response: httpx.Response,
    ) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
        """Parse n8n webhook response.

        Supports:
        1. Streaming format: JSON objects with type: "item" and type: "end"
        2. Non-streaming format: Plain JSON object

        Yields events:
        - {"type": "item", "content": "..."} for streaming chunks
        - {"type": "end"} for streaming completion
        - {"type": "json", "data": {...}, "content": "..."} for non-streaming response
        """
        full_text = ""
        buffer = ""
        decoder = json.JSONDecoder()
        chunk_idx = 0

        async for raw_chunk in response.aiter_bytes():
            if not raw_chunk:
                continue

            try:
                chunk_str = raw_chunk.decode("utf-8", errors="replace")
                full_text += chunk_str
                buffer += chunk_str

                # Try to parse JSON objects from buffer
                while buffer:
                    buffer = buffer.lstrip()
                    if not buffer:
                        break
                    try:
                        obj, idx = decoder.raw_decode(buffer)
                        buffer = buffer[idx:]

                        if not isinstance(obj, dict):
                            continue

                        if obj.get("type") == "item" and "content" in obj:
                            chunk_idx += 1
                            yield {
                                "type": "item",
                                "content": obj["content"],
                                "chunk_idx": chunk_idx,
                            }
                        elif obj.get("type") == "end":
                            yield {"type": "end"}

                    except json.JSONDecodeError:
                        # Incomplete JSON, wait for more data
                        break

            except Exception as e:
                logger.warning(f"Failed to process chunk: {e}")

        # Process remaining buffer after stream ends
        if buffer:
            try:
                buffer = buffer.strip()
                if buffer:
                    obj, _ = decoder.raw_decode(buffer)
                    if isinstance(obj, dict):
                        if obj.get("type") == "item" and "content" in obj:
                            chunk_idx += 1
                            yield {
                                "type": "item",
                                "content": obj["content"],
                                "chunk_idx": chunk_idx,
                            }
                        elif obj.get("type") == "end":
                            yield {"type": "end"}
            except Exception as e:
                logger.warning(f"Failed to parse remaining buffer: {e}")

        # If no streaming chunks were received, parse as non-streaming JSON
        if chunk_idx == 0:
            output_content = self._extract_output(full_text)
            yield {
                "type": "json",
                "content": output_content,
                "raw": full_text,
            }

    def _extract_output(self, response_text: str) -> str:
        """Extract output content from non-streaming response."""
        try:
            response_data = json.loads(response_text.strip())
            if isinstance(response_data, dict):
                if self.output_key in response_data:
                    return response_data[self.output_key]
                else:
                    return json.dumps(response_data, ensure_ascii=False)
            else:
                return response_text
        except json.JSONDecodeError:
            return response_text
