"""Stdio MCP shim that forwards LangBot tool calls to a remote run daemon."""

from __future__ import annotations

import json
import os
import sys
import typing
import urllib.error
import urllib.request

SERVER_INFO = {"name": "langbot-remote-agent", "version": "0.1.0"}


def _write_message(message: dict[str, typing.Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _result(message_id: typing.Any, result: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: typing.Any, code: int, message: str) -> dict[str, typing.Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _daemon_request(
    *,
    endpoint: str,
    run_id: str,
    secret: str,
    method: str,
    params: dict[str, typing.Any],
    timeout: float,
) -> dict[str, typing.Any]:
    payload = json.dumps({"method": method, "params": params}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + f"/run-mcp/{run_id}",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-LangBot-Remote-MCP-Secret": secret,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"invalid daemon MCP response: {e}"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "daemon MCP response must be an object"}
    return data


def handle_message(
    message: dict[str, typing.Any],
    *,
    endpoint: str,
    run_id: str,
    secret: str,
    timeout: float,
) -> dict[str, typing.Any] | None:
    message_id = message.get("id")
    method = str(message.get("method") or "")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if message_id is None:
        return None

    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": str(params.get("protocolVersion") or "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )

    if method == "ping":
        return _result(message_id, {})

    if method in {"tools/list", "tools/call"}:
        response = _daemon_request(
            endpoint=endpoint,
            run_id=run_id,
            secret=secret,
            method=method,
            params=params,
            timeout=timeout,
        )
        if response.get("ok"):
            result = response.get("result")
            return _result(message_id, result if isinstance(result, dict) else {"result": result})
        return _error(message_id, -32000, str(response.get("error") or "LangBot remote MCP error"))

    return _error(message_id, -32601, f"Method not found: {method}")


def main() -> int:
    endpoint = os.environ.get("LANGBOT_REMOTE_MCP_DAEMON_ENDPOINT", "")
    run_id = os.environ.get("LANGBOT_REMOTE_MCP_RUN_ID", "")
    secret = os.environ.get("LANGBOT_REMOTE_MCP_SECRET", "")
    try:
        timeout = float(os.environ.get("LANGBOT_REMOTE_MCP_TIMEOUT", "60") or 60)
    except ValueError:
        timeout = 60.0

    if not endpoint or not run_id or not secret:
        sys.stderr.write(
            "LANGBOT_REMOTE_MCP_DAEMON_ENDPOINT, LANGBOT_REMOTE_MCP_RUN_ID, "
            "and LANGBOT_REMOTE_MCP_SECRET are required\n"
        )
        sys.stderr.flush()
        return 2

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as e:
            _write_message(_error(None, -32700, f"Parse error: {e}"))
            continue
        if not isinstance(message, dict):
            _write_message(_error(None, -32600, "Invalid request"))
            continue

        response = handle_message(
            message,
            endpoint=endpoint,
            run_id=run_id,
            secret=secret,
            timeout=timeout,
        )
        if response is not None:
            _write_message(response)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
