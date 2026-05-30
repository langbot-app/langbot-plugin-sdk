"""MCP adapter for annotated LangBot AgentRunner tools."""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import sys
import threading
import typing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from langbot_plugin.api.agent_tools.external_tools import AgentRunExternalTools
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.proxies.agent_run_api import AgentRunAPIProxy

LANGBOT_AGENT_MCP_SERVER_NAME = "langbot_agent"


def merge_mcp_server_config(
    base_config: dict[str, typing.Any] | None,
    server_config: dict[str, typing.Any],
    *,
    server_name: str = LANGBOT_AGENT_MCP_SERVER_NAME,
) -> dict[str, typing.Any]:
    """Return an MCP config with a LangBot run-scoped server added."""

    data = dict(base_config or {})
    servers = data.get("mcpServers") or data.get("mcp_servers") or {}
    if not isinstance(servers, dict):
        raise ValueError("MCP config mcpServers must be an object")

    merged_servers = dict(servers)
    merged_servers[server_name] = server_config
    data["mcpServers"] = merged_servers
    data.pop("mcp_servers", None)
    return data


class AgentRunMCPBridge:
    """Run-scoped localhost bridge used by stdio MCP proxy processes."""

    def __init__(
        self,
        tools: AgentRunExternalTools,
        *,
        host: str = "127.0.0.1",
        request_timeout: float = 60.0,
        server_name: str = LANGBOT_AGENT_MCP_SERVER_NAME,
    ) -> None:
        self.tools = tools
        self.host = host
        self.request_timeout = request_timeout
        self.server_name = server_name
        self.token = secrets.token_urlsafe(32)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def from_run_api(
        cls,
        api: AgentRunAPIProxy,
        ctx: AgentRunContext,
        *,
        host: str = "127.0.0.1",
        request_timeout: float = 60.0,
        server_name: str = LANGBOT_AGENT_MCP_SERVER_NAME,
    ) -> "AgentRunMCPBridge":
        return cls(
            AgentRunExternalTools(api, ctx),
            host=host,
            request_timeout=request_timeout,
            server_name=server_name,
        )

    @property
    def endpoint(self) -> str:
        if self._server is None:
            raise RuntimeError("LangBot Agent MCP bridge is not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        if self._server is not None:
            return

        self._loop = asyncio.get_running_loop()
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: typing.Any) -> None:
                return

            def do_GET(self) -> None:
                if self.path != "/healthz":
                    self.send_error(404)
                    return
                self._write_json(200, {"ok": True})

            def do_POST(self) -> None:
                if self.path != "/mcp":
                    self.send_error(404)
                    return
                if not hmac.compare_digest(
                    self.headers.get("X-LangBot-Agent-MCP-Token", ""),
                    bridge.token,
                ):
                    self._write_json(401, {"ok": False, "error": "unauthorized"})
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                try:
                    body = self.rfile.read(length).decode("utf-8")
                    payload = json.loads(body) if body else {}
                except Exception as e:
                    self._write_json(400, {"ok": False, "error": f"invalid JSON: {e}"})
                    return
                if not isinstance(payload, dict):
                    self._write_json(400, {"ok": False, "error": "request must be an object"})
                    return

                assert bridge._loop is not None
                future = asyncio.run_coroutine_threadsafe(
                    bridge.handle_mcp_method(
                        str(payload.get("method") or ""),
                        payload.get("params") or {},
                    ),
                    bridge._loop,
                )
                try:
                    result = future.result(timeout=bridge.request_timeout)
                except Exception as e:
                    self._write_json(500, {"ok": False, "error": str(e)})
                    return
                self._write_json(200, {"ok": True, "result": result})

            def _write_json(self, status: int, payload: dict[str, typing.Any]) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer((self.host, 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="langbot-agent-mcp-bridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def mcp_server_config(self) -> dict[str, typing.Any]:
        """Return stdio MCP config for external harnesses."""

        return {
            "command": sys.executable,
            "args": ["-m", "langbot_plugin.api.agent_tools.mcp_stdio"],
            "env": {
                "LANGBOT_AGENT_MCP_ENDPOINT": self.endpoint,
                "LANGBOT_AGENT_MCP_TOKEN": self.token,
            },
        }

    def merged_mcp_config(self, base_config: dict[str, typing.Any] | None = None) -> dict[str, typing.Any]:
        return merge_mcp_server_config(
            base_config,
            self.mcp_server_config(),
            server_name=self.server_name,
        )

    async def handle_mcp_method(self, method: str, params: dict[str, typing.Any]) -> dict[str, typing.Any]:
        if method == "tools/list":
            return {"tools": self.tools.mcp_tools()}
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            return await self.tools.call_mcp_tool(name, arguments)
        raise ValueError(f"Unsupported MCP bridge method: {method}")
