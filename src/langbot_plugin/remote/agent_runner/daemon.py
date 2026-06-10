"""Shared HTTP daemon for remote LangBot AgentRunner execution."""

from __future__ import annotations

import argparse
import asyncio
import collections.abc
import dataclasses
import hmac
import importlib
import json
import os
import pathlib
import re
import select
import secrets
import shlex
import signal
import sys
import threading
import typing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import channel

GENERIC_RUN_SCHEMA = "langbot.remote_agent.run.v1"
LANGBOT_AGENT_MCP_SERVER_NAME = "langbot_agent"
MAX_CAPTURED_OUTPUT_CHARS = 128_000

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|credential|password|secret|token)"
    r"(\s*[:=]\s*)"
    r"([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_INHERITED_ENV_KEYS = {
    "ALL_PROXY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "AWS_ACCESS_KEY_ID",
    "AWS_DEFAULT_REGION",
    "AWS_REGION",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "CURL_CA_BUNDLE",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NO_PROXY",
    "NODE_EXTRA_CA_CERTS",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "VERTEXAI_LOCATION",
    "VERTEXAI_PROJECT",
    "all_proxy",
    "https_proxy",
    "http_proxy",
    "no_proxy",
}

BuildCommand = typing.Callable[[dict[str, typing.Any], str], list[str]]
PrepareRun = typing.Callable[["RemoteRunContext", dict[str, typing.Any]], dict[str, str] | None]


@dataclasses.dataclass(frozen=True)
class ActiveRunChannel:
    run_id: str
    secret: str
    pending_requests: dict[str, asyncio.Future]
    outgoing: asyncio.Queue[dict[str, typing.Any]]

    async def request_mcp(self, method: str, params: dict[str, typing.Any], timeout: float) -> dict[str, typing.Any]:
        request_id = secrets.token_urlsafe(16)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self.pending_requests[request_id] = future
        await self.outgoing.put(
            {
                "type": "mcp.request",
                "request_id": request_id,
                "method": method,
                "params": params,
            }
        )
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.pending_requests.pop(request_id, None)

        if not isinstance(result, dict):
            raise ValueError("MCP channel response must be an object")
        if not result.get("ok"):
            raise ValueError(str(result.get("error") or "remote MCP request failed"))
        payload = result.get("result") or {}
        return payload if isinstance(payload, dict) else {"result": payload}


@dataclasses.dataclass(frozen=True)
class RemoteRunContext:
    workspace_dir: pathlib.Path
    payload: dict[str, typing.Any]
    run_channel: ActiveRunChannel | None = None
    daemon_endpoint: str = ""


@dataclasses.dataclass(frozen=True)
class AgentAdapter:
    name: str
    aliases: tuple[str, ...]
    schemas: tuple[str, ...]
    display_name: str
    build_command: BuildCommand
    prepare_run: PrepareRun | None = None


def safe_name(value: typing.Any, fallback: str = "workspace") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip(".-")
    return (text or fallback)[:96]


def safe_child_path(base_dir: pathlib.Path, relative_path: typing.Any) -> pathlib.Path | None:
    path = pathlib.PurePosixPath(str(relative_path or ""))
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        return None
    base = base_dir.resolve(strict=True)
    target = base.joinpath(*path.parts)
    if not target.resolve(strict=False).is_relative_to(base):
        return None
    return target


def normalize_agent_name(value: typing.Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def parse_args(value: typing.Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def redact_text(value: str) -> str:
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    return _SENSITIVE_KEY_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", value)


def bounded_text(value: str, *, limit: int = MAX_CAPTURED_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def safe_output(value: str, *, limit: int = MAX_CAPTURED_OUTPUT_CHARS) -> str:
    return bounded_text(redact_text(value), limit=limit)


def subprocess_kwargs() -> dict[str, typing.Any]:
    if os.name != "nt":
        return {"start_new_session": True}
    return {}


def terminate_process(process: typing.Any) -> None:
    pid = getattr(process, "pid", None)
    if os.name != "nt" and isinstance(pid, int) and pid > 0:
        try:
            os.killpg(pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    try:
        process.kill()
    except ProcessLookupError:
        pass


def merge_mcp_server_config(
    base_config: dict[str, typing.Any] | None,
    server_config: dict[str, typing.Any],
    *,
    server_name: str = LANGBOT_AGENT_MCP_SERVER_NAME,
) -> dict[str, typing.Any]:
    data = dict(base_config or {})
    servers = data.get("mcpServers") or data.get("mcp_servers") or {}
    if not isinstance(servers, dict):
        raise ValueError("MCP config mcpServers must be an object")

    merged_servers = dict(servers)
    merged_servers[server_name] = server_config
    data["mcpServers"] = merged_servers
    data.pop("mcp_servers", None)
    return data


def add_langbot_mcp_tool_approvals(data: dict[str, typing.Any]) -> None:
    servers = data.get("mcpServers") or data.get("mcp_servers")
    if not isinstance(servers, dict):
        return

    server = servers.get(LANGBOT_AGENT_MCP_SERVER_NAME)
    if not isinstance(server, dict):
        return

    tools = server.setdefault("tools", {})
    if not isinstance(tools, dict):
        tools = {}
        server["tools"] = tools

    for tool_name in (
        "langbot_call_tool",
        "langbot_get_current_event",
        "langbot_history_page",
        "langbot_retrieve_knowledge",
    ):
        tool_config = tools.setdefault(tool_name, {})
        if isinstance(tool_config, dict):
            tool_config.setdefault("approval_mode", "approve")


def subprocess_env(command_path: str = "", extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in _INHERITED_ENV_KEYS}
    home = env.get("HOME") or str(pathlib.Path.home())
    if home:
        env["HOME"] = home
        env.setdefault("USERPROFILE", home)

    path_entries = [
        *parse_args(command_path),
        str(pathlib.Path(home) / ".local" / "bin") if home else "",
        str(pathlib.Path(home) / ".npm-global" / "bin") if home else "",
        env.get("PATH", ""),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    seen: set[str] = set()
    normalized_path: list[str] = []
    for entry in path_entries:
        if entry and entry not in seen:
            normalized_path.append(entry)
            seen.add(entry)
    env["PATH"] = os.pathsep.join(normalized_path)
    if extra_env:
        env.update(extra_env)
    return env


def adapter_registry(adapters: typing.Iterable[AgentAdapter] = ()) -> dict[str, AgentAdapter]:
    registry: dict[str, AgentAdapter] = {}
    for adapter in adapters:
        registry[normalize_agent_name(adapter.name)] = adapter
        for alias in adapter.aliases:
            registry[normalize_agent_name(alias)] = adapter
    return registry


def adapter_by_schema(
    schema: str,
    adapters: typing.Iterable[AgentAdapter] = (),
) -> AgentAdapter | None:
    for adapter in adapters:
        if schema in adapter.schemas:
            return adapter
    return None


def resolve_adapter(
    payload: dict[str, typing.Any],
    *,
    adapters: typing.Iterable[AgentAdapter] = (),
    forced_agent: str = "",
) -> tuple[AgentAdapter | None, dict[str, typing.Any] | None]:
    registry = adapter_registry(adapters)
    schema = str(payload.get("schema") or "")

    if forced_agent:
        adapter = registry.get(normalize_agent_name(forced_agent))
        if adapter is None:
            return None, {"ok": False, "code": "invalid_request", "error": f"unsupported agent: {forced_agent}"}
        if schema not in adapter.schemas and schema != GENERIC_RUN_SCHEMA:
            return None, {"ok": False, "code": "invalid_request", "error": "unsupported request schema"}
        return adapter, None

    if schema == GENERIC_RUN_SCHEMA:
        agent_name = normalize_agent_name(payload.get("agent") or payload.get("agent_type"))
        adapter = registry.get(agent_name)
        if adapter is None:
            return None, {"ok": False, "code": "invalid_request", "error": f"unsupported agent: {agent_name or '<empty>'}"}
        return adapter, None

    adapter = adapter_by_schema(schema, adapters)
    if adapter is None:
        return None, {"ok": False, "code": "invalid_request", "error": "unsupported request schema"}

    configured_agent = payload.get("agent") or payload.get("agent_type")
    if configured_agent and registry.get(normalize_agent_name(configured_agent)) != adapter:
        return None, {"ok": False, "code": "invalid_request", "error": "agent does not match request schema"}
    return adapter, None


def load_adapter(value: str) -> tuple[AgentAdapter, ...]:
    """Load one or more adapters from an import spec.

    The spec format is ``module:attribute``. The attribute may be an
    ``AgentAdapter``, an iterable of ``AgentAdapter`` objects, or a zero-arg
    callable returning either shape.
    """

    spec = str(value or "").strip()
    if ":" not in spec:
        raise ValueError("adapter spec must be in module:attribute format")
    module_name, attribute = spec.split(":", 1)
    if not module_name or not attribute:
        raise ValueError("adapter spec must include module and attribute")

    module = importlib.import_module(module_name)
    loaded = getattr(module, attribute)
    if callable(loaded) and not isinstance(loaded, AgentAdapter):
        loaded = loaded()
    if isinstance(loaded, AgentAdapter):
        return (loaded,)
    if isinstance(loaded, collections.abc.Iterable):
        adapters = tuple(loaded)
        if all(isinstance(adapter, AgentAdapter) for adapter in adapters):
            return adapters
    raise TypeError("adapter spec must resolve to AgentAdapter or iterable of AgentAdapter")


def load_adapters(values: typing.Iterable[str]) -> tuple[AgentAdapter, ...]:
    adapters: list[AgentAdapter] = []
    for value in values:
        adapters.extend(load_adapter(value))
    return tuple(adapters)


def materialize_files(workspace_dir: pathlib.Path, files: list[typing.Any]) -> tuple[bool, str | None]:
    for file_item in files:
        if not isinstance(file_item, dict):
            return False, "file entries must be objects"
        target = safe_child_path(workspace_dir, file_item.get("path"))
        if target is None:
            return False, f"invalid relative file path: {file_item.get('path')}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(file_item.get("content") or ""), encoding="utf-8")
        try:
            mode = int(file_item.get("mode") or 0o644)
            target.chmod(mode & 0o777)
        except (TypeError, ValueError, OSError):
            pass
    return True, None


def local_daemon_endpoint(server_address: tuple[typing.Any, ...]) -> str:
    host, port = server_address[:2]
    host_text = str(host or "127.0.0.1")
    if host_text in {"", "0.0.0.0", "::"}:
        host_text = "127.0.0.1"
    return f"http://{host_text}:{port}"


def write_remote_mcp_config(
    workspace_dir: pathlib.Path,
    payload: dict[str, typing.Any],
    run_channel: ActiveRunChannel,
    daemon_endpoint: str,
) -> tuple[str, dict[str, typing.Any]]:
    context_directory = safe_child_path(
        workspace_dir,
        pathlib.PurePosixPath(".langbot/agent-runner") / safe_name(payload.get("run_id"), "run"),
    )
    if context_directory is None:
        raise ValueError("failed to resolve remote MCP config path")
    context_directory.mkdir(parents=True, exist_ok=True)

    module_root = str(pathlib.Path(__file__).resolve().parents[3])
    python_path = os.pathsep.join(
        item for item in (module_root, os.environ.get("PYTHONPATH", "")) if item
    )
    server_config = {
        "command": sys.executable,
        "args": ["-m", "langbot_plugin.remote.agent_runner.mcp_stdio"],
        "env": {
            "LANGBOT_REMOTE_MCP_DAEMON_ENDPOINT": daemon_endpoint,
            "LANGBOT_REMOTE_MCP_RUN_ID": run_channel.run_id,
            "LANGBOT_REMOTE_MCP_SECRET": run_channel.secret,
            "PYTHONPATH": python_path,
        },
    }
    data = merge_mcp_server_config({}, server_config)
    add_langbot_mcp_tool_approvals(data)

    mcp_path = context_directory / "mcp.json"
    mcp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        mcp_path.chmod(0o600)
    except OSError:
        pass
    return str(mcp_path), data


async def run_subprocess(
    command: list[str],
    stdin: str,
    timeout: float,
    cwd: pathlib.Path,
    command_path: str = "",
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
        env=subprocess_env(command_path, extra_env),
        **subprocess_kwargs(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin.encode("utf-8")),
            timeout=timeout,
        )
    except TimeoutError:
        terminate_process(process)
        await process.wait()
        raise
    except asyncio.CancelledError:
        terminate_process(process)
        await process.wait()
        raise

    return (
        process.returncode or 0,
        safe_output(stdout.decode("utf-8", errors="replace")),
        safe_output(stderr.decode("utf-8", errors="replace")),
    )


async def handle_run_request(
    payload: dict[str, typing.Any],
    base_dir: pathlib.Path,
    command_path: str = "",
    *,
    forced_agent: str = "",
    adapters: typing.Iterable[AgentAdapter] = (),
) -> dict[str, typing.Any]:
    adapter, error = resolve_adapter(payload, adapters=adapters, forced_agent=forced_agent)
    if error is not None:
        return error
    assert adapter is not None

    return await execute_run_payload(
        payload,
        adapter,
        base_dir,
        command_path,
    )


async def execute_run_payload(
    payload: dict[str, typing.Any],
    adapter: AgentAdapter,
    base_dir: pathlib.Path,
    command_path: str = "",
    *,
    run_channel: ActiveRunChannel | None = None,
    daemon_endpoint: str = "",
) -> dict[str, typing.Any]:
    if run_channel is not None and not daemon_endpoint:
        return {"ok": False, "code": "invalid_request", "error": "daemon endpoint is required for channel runs"}

    workspace_key = str(payload.get("workspace_key") or "default")
    workspace_dir = base_dir / safe_name(workspace_key, "workspace")
    workspace_dir.mkdir(parents=True, exist_ok=True)

    files = payload.get("files") or []
    if not isinstance(files, list):
        return {"ok": False, "code": "invalid_request", "error": "files must be an array"}
    ok, materialize_error = materialize_files(workspace_dir, files)
    if not ok:
        return {"ok": False, "code": "invalid_request", "error": materialize_error or "failed to materialize files"}

    config = payload.get("config") or {}
    if not isinstance(config, dict):
        return {"ok": False, "code": "invalid_request", "error": "config must be an object"}
    config = dict(config)

    extra_env: dict[str, str] = {}
    if adapter.prepare_run is not None:
        context = RemoteRunContext(
            workspace_dir=workspace_dir,
            payload=payload,
            run_channel=run_channel,
            daemon_endpoint=daemon_endpoint,
        )
        try:
            prepared_env = adapter.prepare_run(context, config)
        except Exception as e:
            return {"ok": False, "code": "adapter_prepare_error", "error": str(e)}
        if prepared_env:
            extra_env.update(prepared_env)

    command = adapter.build_command(
        config,
        str(payload.get("resume_session_id") or ""),
    )
    timeout = float(payload.get("timeout") or config.get("timeout") or 300)

    try:
        returncode, stdout, stderr = await run_subprocess(
            command,
            str(payload.get("stdin") or ""),
            timeout,
            workspace_dir,
            command_path,
            extra_env,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "code": "command_not_found",
            "error": f"{adapter.display_name} CLI command not found: {command[0]}",
        }
    except TimeoutError:
        return {
            "ok": False,
            "code": "timeout",
            "error": f"{adapter.display_name} CLI timed out after {timeout} seconds",
            "retryable": True,
        }
    except Exception as e:
        return {
            "ok": False,
            "code": "remote_daemon_error",
            "error": str(e),
        }

    return {
        "ok": True,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "working_directory": str(workspace_dir),
    }


class RemoteAgentHandler(BaseHTTPRequestHandler):
    server: RemoteAgentHTTPServer

    def log_message(self, format: str, *args: typing.Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path == channel.RUN_CHANNEL_PATH:
            self._handle_run_channel()
            return
        if self.path != "/healthz":
            self.send_error(404)
            return
        self._write_json(200, {"ok": True})

    def do_POST(self) -> None:
        if self.path.startswith("/run-mcp/"):
            self._handle_run_mcp()
            return
        if self.path != "/run":
            self.send_error(404)
            return
        if not self._authorized():
            self._write_json(401, {"ok": False, "code": "unauthorized", "error": "unauthorized"})
            return

        payload = self._read_json_body()
        if not isinstance(payload, dict):
            return

        future = asyncio.run_coroutine_threadsafe(
            handle_run_request(
                payload,
                self.server.base_dir,
                self.server.command_path,
                forced_agent=self.server.forced_agent,
                adapters=self.server.adapters,
            ),
            self.server.loop,
        )
        try:
            result = future.result(timeout=self.server.handler_timeout)
        except Exception as e:
            result = {"ok": False, "code": "remote_daemon_error", "error": str(e)}
        self._write_json(200, result)

    def _authorized(self) -> bool:
        if not self.server.token:
            return True
        header = self.headers.get("Authorization", "")
        return hmac.compare_digest(header, f"Bearer {self.server.token}")

    def _read_json_body(self) -> dict[str, typing.Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > self.server.max_request_bytes:
            self._write_json(413, {"ok": False, "code": "payload_too_large", "error": "request is too large"})
            return None

        try:
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body) if body else {}
        except Exception as e:
            self._write_json(400, {"ok": False, "code": "invalid_request", "error": f"invalid JSON: {e}"})
            return None
        if not isinstance(payload, dict):
            self._write_json(400, {"ok": False, "code": "invalid_request", "error": "request must be an object"})
            return None
        return payload

    def _handle_run_mcp(self) -> None:
        run_id = self.path.rsplit("/", 1)[-1]
        secret = self.headers.get("X-LangBot-Remote-MCP-Secret", "")
        payload = self._read_json_body()
        if not isinstance(payload, dict):
            return

        future = asyncio.run_coroutine_threadsafe(
            self.server.handle_mcp_request(
                run_id,
                secret,
                str(payload.get("method") or ""),
                payload.get("params") if isinstance(payload.get("params"), dict) else {},
            ),
            self.server.loop,
        )
        try:
            result = future.result(timeout=self.server.mcp_request_timeout + 5)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        self._write_json(200, result)

    def _handle_run_channel(self) -> None:
        if not self._authorized():
            self._write_json(401, {"ok": False, "code": "unauthorized", "error": "unauthorized"})
            return

        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            self.send_error(400, "missing Sec-WebSocket-Key")
            return

        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", channel.websocket_accept_key(key))
        self.end_headers()
        self.close_connection = True

        try:
            opcode, payload = channel.read_ws_frame_sync(self.rfile)
            message = channel.decode_ws_json(opcode, payload)
            if not message or message.get("type") != "run.start":
                raise ValueError("first channel message must be run.start")
            run_payload = message.get("payload") or {}
            if not isinstance(run_payload, dict):
                raise ValueError("run.start payload must be an object")

            session = self.server.create_run_channel(str(run_payload.get("run_id") or "run"))
            future = asyncio.run_coroutine_threadsafe(
                self.server.handle_channel_run(run_payload, session),
                self.server.loop,
            )
            try:
                self._run_channel_loop(session, future)
            finally:
                self._cancel_run_future(future)
                self.server.remove_run_channel(session.run_id)
        except EOFError:
            pass
        except Exception as e:
            try:
                self._write_ws_json({"type": "run.failed", "error": {"code": "remote_daemon_error", "error": str(e)}})
            except OSError:
                pass

    def _run_channel_loop(self, session: ActiveRunChannel, future: typing.Any) -> None:
        try:
            while True:
                self._read_pending_channel_messages(session)
                outgoing_future = asyncio.run_coroutine_threadsafe(session.outgoing.get(), self.server.loop)
                try:
                    outgoing = outgoing_future.result(timeout=0.05)
                except TimeoutError:
                    outgoing_future.cancel()
                    if future.done():
                        response = future.result()
                        self._write_ws_json({"type": "run.completed", "response": response})
                        return
                    continue

                self._write_ws_json(outgoing)
                if outgoing.get("type") == "mcp.request":
                    self._read_channel_response(session)
        except EOFError:
            self._cancel_run_future(future)
            raise
        except Exception:
            self._cancel_run_future(future)
            raise

    def _cancel_run_future(self, future: typing.Any) -> None:
        if not future.done():
            future.cancel()

    def _read_pending_channel_messages(self, session: ActiveRunChannel) -> None:
        while True:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return
            self._read_channel_response(session)

    def _read_channel_response(self, session: ActiveRunChannel) -> None:
        opcode, payload = channel.read_ws_frame_sync(self.rfile)
        message = channel.decode_ws_json(opcode, payload)
        if message is None:
            raise EOFError("run channel closed")
        if message.get("type") != "mcp.response":
            return
        request_id = str(message.get("request_id") or "")
        asyncio.run_coroutine_threadsafe(
            self.server.resolve_mcp_response(request_id, message),
            self.server.loop,
        ).result(timeout=1)

    def _write_ws_json(self, message: dict[str, typing.Any]) -> None:
        self.wfile.write(channel.encode_ws_text(message, mask=False))
        self.wfile.flush()

    def _write_json(self, status: int, payload: dict[str, typing.Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class RemoteAgentHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        base_dir: pathlib.Path,
        token: str = "",
        command_path: str = "",
        max_request_bytes: int = 10 * 1024 * 1024,
        handler_timeout: float = 900,
        forced_agent: str = "",
        adapters: typing.Iterable[AgentAdapter] = (),
        loop_thread_name: str = "langbot-remote-agent-loop",
    ) -> None:
        super().__init__(server_address, RemoteAgentHandler)
        self.base_dir = base_dir
        self.token = token
        self.command_path = command_path
        self.max_request_bytes = max_request_bytes
        self.handler_timeout = handler_timeout
        self.mcp_request_timeout = 60.0
        self.forced_agent = forced_agent
        self.adapters = tuple(adapters)
        self.active_channels: dict[str, ActiveRunChannel] = {}
        self.loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop,
            name=loop_thread_name,
            daemon=True,
        )
        self._loop_thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def create_run_channel(self, run_id: str) -> ActiveRunChannel:
        session = ActiveRunChannel(
            run_id=run_id,
            secret=secrets.token_urlsafe(32),
            pending_requests={},
            outgoing=asyncio.Queue(),
        )
        future = asyncio.run_coroutine_threadsafe(self._register_run_channel(session), self.loop)
        future.result(timeout=2)
        return session

    async def _register_run_channel(self, session: ActiveRunChannel) -> None:
        self.active_channels[session.run_id] = session

    def remove_run_channel(self, run_id: str) -> None:
        future = asyncio.run_coroutine_threadsafe(self._remove_run_channel(run_id), self.loop)
        future.result(timeout=2)

    async def _remove_run_channel(self, run_id: str) -> None:
        session = self.active_channels.pop(run_id, None)
        if session is None:
            return
        for future in session.pending_requests.values():
            if not future.done():
                future.set_result({"ok": False, "error": "remote run channel closed"})
        session.pending_requests.clear()

    async def resolve_mcp_response(self, request_id: str, message: dict[str, typing.Any]) -> None:
        for session in self.active_channels.values():
            future = session.pending_requests.get(request_id)
            if future is not None and not future.done():
                future.set_result(message)
                return

    async def handle_mcp_request(
        self,
        run_id: str,
        secret: str,
        method: str,
        params: dict[str, typing.Any],
    ) -> dict[str, typing.Any]:
        session = self.active_channels.get(run_id)
        if session is None:
            return {"ok": False, "error": "remote run channel is not active"}
        if not hmac.compare_digest(secret, session.secret):
            return {"ok": False, "error": "unauthorized"}
        try:
            result = await session.request_mcp(method, params, timeout=self.mcp_request_timeout)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "result": result}

    async def handle_channel_run(
        self,
        payload: dict[str, typing.Any],
        session: ActiveRunChannel,
    ) -> dict[str, typing.Any]:
        adapter, error = resolve_adapter(payload, adapters=self.adapters, forced_agent=self.forced_agent)
        if error is not None:
            return error
        assert adapter is not None
        return await execute_run_payload(
            payload,
            adapter,
            self.base_dir,
            self.command_path,
            run_channel=session,
            daemon_endpoint=local_daemon_endpoint(self.server_address),
        )

    def server_close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._loop_thread.join(timeout=2)
        self.loop.close()
        super().server_close()


def serve(
    *,
    host: str,
    port: int,
    base_dir: pathlib.Path,
    token: str = "",
    command_path: str = "",
    max_request_bytes: int = 10 * 1024 * 1024,
    forced_agent: str = "",
    adapters: typing.Iterable[AgentAdapter] = (),
    label: str = "LangBot remote agent",
) -> int:
    server = RemoteAgentHTTPServer(
        (host, port),
        base_dir=base_dir,
        token=token,
        command_path=command_path,
        max_request_bytes=max_request_bytes,
        forced_agent=forced_agent,
        adapters=adapters,
    )
    print(f"{label} daemon listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.shutdown()
        server.server_close()
    return 0


def _positive_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def build_arg_parser(
    *,
    description: str = "Run the shared LangBot remote agent daemon.",
    env_prefix: str = "LANGBOT_REMOTE_AGENT",
    default_port: int = 8764,
    include_agent: bool = True,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default=os.getenv(f"{env_prefix}_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=_positive_int_env(f"{env_prefix}_PORT", default_port))
    parser.add_argument(
        "--base-dir",
        default=os.getenv(f"{env_prefix}_BASE_DIR", ""),
        help="Base directory where daemon workspaces are created.",
    )
    parser.add_argument("--token", default=os.getenv(f"{env_prefix}_TOKEN", ""))
    parser.add_argument(
        "--command-path",
        default=os.getenv(f"{env_prefix}_COMMAND_PATH", ""),
        help="Optional os.pathsep-separated PATH entries to prepend when executing agent CLIs.",
    )
    parser.add_argument(
        "--adapter",
        action="append",
        default=parse_args(os.getenv(f"{env_prefix}_ADAPTERS", "")),
        help="Import path for a remote AgentRunner adapter, e.g. my_pkg.remote:adapter. May be repeated.",
    )
    if include_agent:
        parser.add_argument(
            "--agent",
            default=os.getenv(f"{env_prefix}_AGENT", ""),
            help="Optional adapter name to force for all requests.",
        )
    parser.add_argument("--max-request-mb", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if not args.base_dir:
        parser.error("--base-dir or LANGBOT_REMOTE_AGENT_BASE_DIR is required")
    try:
        adapters = load_adapters(args.adapter)
    except Exception as e:
        parser.error(str(e))
    if not adapters:
        parser.error("--adapter or LANGBOT_REMOTE_AGENT_ADAPTERS is required")

    base_dir = pathlib.Path(args.base_dir).expanduser().resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    return serve(
        host=args.host,
        port=args.port,
        base_dir=base_dir,
        token=args.token,
        command_path=args.command_path,
        max_request_bytes=args.max_request_mb * 1024 * 1024,
        forced_agent=args.agent,
        adapters=adapters,
        label="LangBot remote agent",
    )


def compatibility_main(
    *,
    argv: list[str] | None = None,
    agent: str,
    env_prefix: str,
    default_port: int,
    description: str,
    label: str,
    command_help_name: str,
    adapters: typing.Iterable[AgentAdapter],
) -> int:
    parser = build_arg_parser(
        description=description,
        env_prefix=env_prefix,
        default_port=default_port,
        include_agent=False,
    )
    for action in parser._actions:
        if action.dest == "command_path":
            action.help = f"Optional os.pathsep-separated PATH entries to prepend when executing {command_help_name}."
    args = parser.parse_args(argv)

    if not args.base_dir:
        parser.error(f"--base-dir or {env_prefix}_BASE_DIR is required")
    try:
        loaded_adapters = (*tuple(adapters), *load_adapters(args.adapter))
    except Exception as e:
        parser.error(str(e))
    base_dir = pathlib.Path(args.base_dir).expanduser().resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    return serve(
        host=args.host,
        port=args.port,
        base_dir=base_dir,
        token=args.token,
        command_path=args.command_path,
        max_request_bytes=args.max_request_mb * 1024 * 1024,
        forced_agent=agent,
        adapters=loaded_adapters,
        label=label,
    )
