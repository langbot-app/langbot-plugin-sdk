"""Long-lived MCP gateway for run-scoped LangBot assets."""

from __future__ import annotations

import asyncio
import dataclasses
import hmac
import json
import secrets
import threading
import time
import typing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from langbot_plugin.api.agent_tools.external_tools import AgentRunExternalTools
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.proxies.agent_run_api import AgentRunAPIProxy

LANGBOT_AGENT_GATEWAY_SERVER_NAME = "langbot_agent"
LANGBOT_AGENT_GATEWAY_INFO = {"name": "langbot-agent-gateway", "version": "0.1.0"}
DEFAULT_RUN_TOKEN_TTL_SECONDS = 3600.0


@dataclasses.dataclass
class AgentAssetGatewayRegistration:
    """A short-lived run registration inside a long-lived asset gateway."""

    gateway: "AgentAssetGateway"
    token: str
    tools: AgentRunExternalTools
    loop: asyncio.AbstractEventLoop
    expires_at: float

    @property
    def server_name(self) -> str:
        return self.gateway.server_name

    @property
    def endpoint(self) -> str:
        return self.gateway.endpoint

    @property
    def http_mcp_endpoint(self) -> str:
        return self.gateway.http_mcp_endpoint

    def http_mcp_server_config(
        self,
        *,
        public_url: str | None = None,
        transport: str = "http",
        include_token_header: bool = True,
    ) -> dict[str, typing.Any]:
        headers = {}
        if include_token_header:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "X-LangBot-Agent-Gateway-Token": self.token,
            }
        return {
            "name": self.server_name,
            "url": (public_url or self.http_mcp_endpoint).strip(),
            "type": transport,
            "transport": transport,
            "headers": headers,
        }

    def stop(self) -> None:
        self.gateway.unregister_run(self.token)


class AgentAssetGateway:
    """Process-long HTTP MCP gateway with per-run authorization tokens."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        request_timeout: float = 60.0,
        server_name: str = LANGBOT_AGENT_GATEWAY_SERVER_NAME,
    ) -> None:
        self.host = host
        self.port = port
        self.request_timeout = request_timeout
        self.server_name = server_name
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._registrations: dict[str, AgentAssetGatewayRegistration] = {}
        self._lock = threading.RLock()

    @property
    def endpoint(self) -> str:
        if self._server is None:
            raise RuntimeError("LangBot Agent Asset Gateway is not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def http_mcp_endpoint(self) -> str:
        return f"{self.endpoint}/mcp"

    def start(self) -> None:
        if self._server is not None:
            return

        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: typing.Any) -> None:
                return

            def do_GET(self) -> None:
                if self.path != "/healthz":
                    self.send_error(404)
                    return
                self._write_json(200, {"ok": True})

            def do_POST(self) -> None:
                if self.path not in {"/mcp", "/mcp/http"}:
                    self.send_error(404)
                    return

                payload = self._read_json_payload()
                if isinstance(payload, Exception):
                    self._write_json(
                        400, {"ok": False, "error": f"invalid JSON: {payload}"}
                    )
                    return

                try:
                    result = gateway.handle_http_mcp_request(
                        payload,
                        header_token=self._header_token(),
                    )
                except Exception as e:
                    self._write_json(500, _jsonrpc_error(None, -32000, str(e)))
                    return
                if result is None:
                    self._write_empty(202)
                    return
                self._write_json(200, result)

            def do_DELETE(self) -> None:
                if self.path not in {"/mcp", "/mcp/http"}:
                    self.send_error(404)
                    return
                self.send_response(405)
                self.send_header("Allow", "GET, POST")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _header_token(self) -> str:
                authorization = self.headers.get("Authorization", "").strip()
                if authorization.lower().startswith("bearer "):
                    return authorization[7:].strip()
                for name in (
                    "X-LangBot-Agent-Gateway-Token",
                    "X-LangBot-Agent-MCP-Token",
                ):
                    token = self.headers.get(name, "").strip()
                    if token:
                        return token
                return ""

            def _read_json_payload(self) -> typing.Any:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                try:
                    body = self.rfile.read(length).decode("utf-8")
                    return json.loads(body) if body else {}
                except Exception as e:
                    return e

            def _write_json(self, status: int, payload: typing.Any) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _write_empty(self, status: int) -> None:
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="langbot-agent-asset-gateway",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        with self._lock:
            self._registrations.clear()
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def register_run(
        self,
        api: AgentRunAPIProxy,
        ctx: AgentRunContext,
        *,
        token: str | None = None,
        ttl_seconds: float = DEFAULT_RUN_TOKEN_TTL_SECONDS,
    ) -> AgentAssetGatewayRegistration:
        self.start()
        run_token = token or secrets.token_urlsafe(32)
        registration = AgentAssetGatewayRegistration(
            gateway=self,
            token=run_token,
            tools=AgentRunExternalTools(api, ctx),
            loop=asyncio.get_running_loop(),
            expires_at=time.monotonic() + max(1.0, ttl_seconds),
        )
        with self._lock:
            self._registrations[run_token] = registration
        return registration

    def unregister_run(self, token: str) -> None:
        with self._lock:
            self._registrations.pop(token, None)

    def has_active_registrations(self) -> bool:
        self._cleanup_expired_registrations()
        with self._lock:
            return bool(self._registrations)

    def matches_config(
        self,
        *,
        host: str,
        port: int,
        server_name: str,
    ) -> bool:
        return (
            self.host == host
            and self.port == port
            and self.server_name == server_name
        )

    def handle_http_mcp_request(
        self,
        payload: typing.Any,
        *,
        header_token: str = "",
    ) -> dict[str, typing.Any] | list[dict[str, typing.Any]] | None:
        if isinstance(payload, list):
            if not payload:
                return _jsonrpc_error(None, -32600, "Invalid request")
            responses: list[dict[str, typing.Any]] = []
            for item in payload:
                response = self._handle_http_mcp_message(
                    item,
                    header_token=header_token,
                )
                if response is not None:
                    responses.append(response)
            return responses or None
        return self._handle_http_mcp_message(payload, header_token=header_token)

    def _handle_http_mcp_message(
        self,
        message: typing.Any,
        *,
        header_token: str,
    ) -> dict[str, typing.Any] | None:
        if not isinstance(message, dict):
            return _jsonrpc_error(None, -32600, "Invalid request")

        message_id = message.get("id")
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        if message_id is None:
            return None

        if method == "initialize":
            return _jsonrpc_result(
                message_id,
                {
                    "protocolVersion": str(
                        params.get("protocolVersion") or "2025-06-18"
                    ),
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        }
                    },
                    "serverInfo": LANGBOT_AGENT_GATEWAY_INFO,
                    "instructions": (
                        "Use langbot_list_assets to discover run-authorized "
                        "LangBot assets. Tool calls are scoped by the MCP "
                        "Authorization header or by the run_token argument."
                    ),
                },
            )
        if method == "ping":
            return _jsonrpc_result(message_id, {})
        if method == "tools/list":
            return _jsonrpc_result(
                message_id,
                {"tools": AgentRunExternalTools.all_mcp_tools(include_run_token=True)},
            )
        if method == "tools/call":
            return _jsonrpc_result(
                message_id,
                self._call_tool(params, header_token=header_token),
            )
        return _jsonrpc_error(message_id, -32601, f"Method not found: {method}")

    def _call_tool(
        self,
        params: dict[str, typing.Any],
        *,
        header_token: str,
    ) -> dict[str, typing.Any]:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        arguments = dict(arguments)
        argument_token = str(arguments.pop("run_token", "") or "").strip()
        token = argument_token or header_token
        registration = self._registration_for_token(token)
        if registration is None:
            return _mcp_tool_error("A valid LangBot run_token is required")

        future = asyncio.run_coroutine_threadsafe(
            registration.tools.call_mcp_tool(name, arguments),
            registration.loop,
        )
        try:
            return future.result(timeout=self.request_timeout)
        except Exception as e:
            return _mcp_tool_error(str(e))

    def _registration_for_token(
        self, token: str
    ) -> AgentAssetGatewayRegistration | None:
        if not token:
            return None
        self._cleanup_expired_registrations()
        with self._lock:
            registration = self._registrations.get(token)
            if registration is None:
                return None
            if not hmac.compare_digest(registration.token, token):
                return None
            return registration

    def _cleanup_expired_registrations(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [
                item_token
                for item_token, item in self._registrations.items()
                if item.expires_at <= now
            ]
            for item_token in expired:
                self._registrations.pop(item_token, None)


_default_gateway: AgentAssetGateway | None = None
_default_gateway_lock = threading.Lock()


def get_default_agent_asset_gateway(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    request_timeout: float = 60.0,
    server_name: str = LANGBOT_AGENT_GATEWAY_SERVER_NAME,
) -> AgentAssetGateway:
    global _default_gateway
    with _default_gateway_lock:
        if (
            _default_gateway is not None
            and not _default_gateway.matches_config(
                host=host,
                port=port,
                server_name=server_name,
            )
            and not _default_gateway.has_active_registrations()
        ):
            _default_gateway.stop()
            _default_gateway = None

        if _default_gateway is None:
            _default_gateway = AgentAssetGateway(
                host=host,
                port=port,
                request_timeout=request_timeout,
                server_name=server_name,
            )
        else:
            _default_gateway.request_timeout = request_timeout
        _default_gateway.start()
        return _default_gateway


def _mcp_tool_error(message: str) -> dict[str, typing.Any]:
    return {
        "isError": True,
        "content": [
            {
                "type": "text",
                "text": message,
            }
        ],
    }


def _jsonrpc_result(
    message_id: typing.Any,
    result: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(
    message_id: typing.Any,
    code: int,
    message: str,
) -> dict[str, typing.Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
