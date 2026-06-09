"""Shared bidirectional run channel helpers for remote AgentRunner daemons."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import typing
import urllib.parse

RUN_CHANNEL_PATH = "/run-channel"
RUN_CHANNEL_SCHEMA = "langbot.remote_agent.run_channel.v1"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

MCPHandler = typing.Callable[[str, dict[str, typing.Any]], typing.Awaitable[dict[str, typing.Any]]]


class WebSocketProtocolError(RuntimeError):
    """Raised when the minimal WebSocket transport receives invalid frames."""


def websocket_accept_key(key: str) -> str:
    digest = hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_ws_frame(payload: bytes, *, opcode: int = 1, mask: bool = False) -> bytes:
    first = 0x80 | (opcode & 0x0F)
    length = len(payload)
    if length < 126:
        header = bytes([first, (0x80 if mask else 0) | length])
    elif length < 65536:
        header = bytes([first, (0x80 if mask else 0) | 126]) + struct.pack("!H", length)
    else:
        header = bytes([first, (0x80 if mask else 0) | 127]) + struct.pack("!Q", length)

    if not mask:
        return header + payload

    key = os.urandom(4)
    masked = bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))
    return header + key + masked


def encode_ws_text(message: dict[str, typing.Any], *, mask: bool = False) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return encode_ws_frame(payload, opcode=1, mask=mask)


def encode_ws_close(*, mask: bool = False) -> bytes:
    return encode_ws_frame(b"", opcode=8, mask=mask)


def _read_exact_sync(stream: typing.BinaryIO, count: int) -> bytes:
    data = stream.read(count)
    if len(data) != count:
        raise EOFError("websocket connection closed")
    return data


def read_ws_frame_sync(stream: typing.BinaryIO) -> tuple[int, bytes]:
    header = _read_exact_sync(stream, 2)
    first, second = header
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact_sync(stream, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact_sync(stream, 8))[0]

    mask_key = _read_exact_sync(stream, 4) if masked else b""
    payload = _read_exact_sync(stream, length) if length else b""
    if masked:
        payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


async def read_ws_frame_async(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(2)
    first, second = header
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]

    mask_key = await reader.readexactly(4) if masked else b""
    payload = await reader.readexactly(length) if length else b""
    if masked:
        payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


def decode_ws_json(opcode: int, payload: bytes) -> dict[str, typing.Any] | None:
    if opcode == 8:
        return None
    if opcode != 1:
        raise WebSocketProtocolError(f"unsupported websocket opcode: {opcode}")
    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise WebSocketProtocolError(f"invalid websocket JSON payload: {e}") from e
    if not isinstance(data, dict):
        raise WebSocketProtocolError("websocket JSON payload must be an object")
    return data


def channel_url(endpoint: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(endpoint.strip())
    if parsed.scheme in {"ws", "wss"}:
        scheme = parsed.scheme
    elif parsed.scheme == "https":
        scheme = "wss"
    else:
        scheme = "ws"

    netloc = parsed.netloc or parsed.path
    if not netloc:
        raise ValueError("remote endpoint must include a host")

    base_path = parsed.path if parsed.netloc else ""
    path = base_path.rstrip("/") + RUN_CHANNEL_PATH
    return urllib.parse.urlparse(urllib.parse.urlunparse((scheme, netloc, path, "", "", "")))


async def run_remote_channel(
    endpoint: str,
    token: str,
    request_payload: dict[str, typing.Any],
    timeout: float,
    *,
    mcp_handler: MCPHandler | None = None,
) -> dict[str, typing.Any]:
    """Run a remote agent request over the shared bidirectional channel."""

    try:
        return await asyncio.wait_for(
            _run_remote_channel(endpoint, token, request_payload, mcp_handler=mcp_handler),
            timeout=timeout,
        )
    except TimeoutError:
        return {
            "ok": False,
            "code": "connection_timeout",
            "error": f"remote run channel timed out after {timeout} seconds",
            "retryable": True,
        }
    except Exception as e:
        return {"ok": False, "code": "connection_error", "error": str(e), "retryable": True}


async def _run_remote_channel(
    endpoint: str,
    token: str,
    request_payload: dict[str, typing.Any],
    *,
    mcp_handler: MCPHandler | None = None,
) -> dict[str, typing.Any]:
    url = channel_url(endpoint)
    host = url.hostname or ""
    if not host:
        raise ValueError("remote endpoint must include a host")
    port = url.port or (443 if url.scheme == "wss" else 80)
    target = url.path or RUN_CHANNEL_PATH
    ssl_context: ssl.SSLContext | bool | None = True if url.scheme == "wss" else None

    reader, writer = await asyncio.open_connection(host, port, ssl=ssl_context)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        headers = [
            f"GET {target} HTTP/1.1",
            f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Version: 13",
            f"Sec-WebSocket-Key: {key}",
        ]
        if token:
            headers.append(f"Authorization: Bearer {token}")
        writer.write(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
        await writer.drain()

        response = await reader.readuntil(b"\r\n\r\n")
        status_line = response.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        if " 101 " not in status_line:
            raise ConnectionError(f"remote daemon did not accept run channel: {status_line}")

        writer.write(encode_ws_text({"type": "run.start", "payload": request_payload}, mask=True))
        await writer.drain()

        while True:
            opcode, payload = await read_ws_frame_async(reader)
            message = decode_ws_json(opcode, payload)
            if message is None:
                return {"ok": False, "code": "connection_closed", "error": "remote run channel closed"}

            message_type = str(message.get("type") or "")
            if message_type == "run.completed":
                response_payload = message.get("response") or {}
                if isinstance(response_payload, dict):
                    return response_payload
                return {"ok": False, "code": "invalid_response", "error": "run.completed response must be an object"}

            if message_type == "run.failed":
                error_payload = message.get("error") or {}
                if isinstance(error_payload, dict):
                    return {"ok": False, **error_payload}
                return {"ok": False, "code": "remote_error", "error": str(error_payload)}

            if message_type == "mcp.request":
                await _handle_mcp_request(message, writer, mcp_handler)
                continue

            if message_type == "ping":
                writer.write(encode_ws_text({"type": "pong"}, mask=True))
                await writer.drain()
    finally:
        writer.write(encode_ws_close(mask=True))
        await writer.drain()
        writer.close()
        await writer.wait_closed()


async def _handle_mcp_request(
    message: dict[str, typing.Any],
    writer: asyncio.StreamWriter,
    mcp_handler: MCPHandler | None,
) -> None:
    request_id = str(message.get("request_id") or "")
    method = str(message.get("method") or "")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if not mcp_handler:
        response: dict[str, typing.Any] = {
            "type": "mcp.response",
            "request_id": request_id,
            "ok": False,
            "error": "LangBot MCP bridge is not available for this run",
        }
    else:
        try:
            result = await mcp_handler(method, params)
        except Exception as e:
            response = {
                "type": "mcp.response",
                "request_id": request_id,
                "ok": False,
                "error": str(e),
            }
        else:
            response = {
                "type": "mcp.response",
                "request_id": request_id,
                "ok": True,
                "result": result,
            }

    writer.write(encode_ws_text(response, mask=True))
    await writer.drain()


def is_socket_timeout(error: BaseException) -> bool:
    return isinstance(error, (TimeoutError, socket.timeout))
