from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from langbot_plugin.runtime.io.connections.stdio import StdioConnection
from langbot_plugin.runtime.io.connections.ws import WebSocketConnection
from langbot_plugin.runtime.io.controllers.stdio import client as stdio_client
from langbot_plugin.runtime.io.controllers.stdio import server as stdio_server
from langbot_plugin.runtime.io.controllers.ws import client as ws_client
from langbot_plugin.runtime.io.controllers.ws import server as ws_server


class FakeProcess:
    def __init__(self, stdin=object(), stdout=object()):
        self.stdin = stdin
        self.stdout = stdout
        self.returncode = 0


class FakeWebSocket:
    remote_address = ("127.0.0.1", 12345)


class FakeWebSocketConnectContext:
    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeServer:
    def __init__(self):
        self.waited = False
        self.closed = False

    async def wait_closed(self):
        self.waited = True

    def close(self):
        self.closed = True


async def test_stdio_client_controller_creates_process_connection(monkeypatch):
    process = FakeProcess()
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return process

    async def callback(connection):
        captured["connection"] = connection

    monkeypatch.setattr(
        stdio_client.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    controller = stdio_client.StdioClientController(
        command="python",
        args=["plugin.py"],
        env={"TOKEN": "secret"},
        working_dir="/tmp/plugin",
    )

    await controller.run(callback)

    assert captured["args"][:2] == ("python", "plugin.py")
    assert captured["kwargs"]["env"] == {"TOKEN": "secret"}
    assert captured["kwargs"]["cwd"] == "/tmp/plugin"
    assert captured["kwargs"]["stderr"] is None
    assert isinstance(captured["connection"], StdioConnection)
    assert captured["connection"].process is process


async def test_stdio_client_controller_captures_stderr_only_when_requested(
    monkeypatch,
):
    process = FakeProcess()
    captured = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured.update(kwargs)
        return process

    async def callback(connection):
        return None

    monkeypatch.setattr(
        stdio_client.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    controller = stdio_client.StdioClientController(
        "python",
        [],
        {},
        capture_stderr=True,
    )

    await controller.run(callback)

    assert captured["stderr"] is stdio_client.asyncio.subprocess.PIPE


async def test_stdio_client_controller_rejects_missing_pipes(monkeypatch):
    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess(stdin=None, stdout=object())

    monkeypatch.setattr(
        stdio_client.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    controller = stdio_client.StdioClientController("python", [], {}, ".")

    with pytest.raises(RuntimeError, match="Failed to create subprocess pipes"):
        await controller.run(lambda connection: None)


async def test_stdio_server_controller_wraps_standard_streams(monkeypatch):
    captured = {}

    async def fake_connect_stdin_stdout():
        return object(), object()

    async def callback(connection):
        captured["connection"] = connection

    monkeypatch.setattr(
        stdio_server,
        "connect_stdin_stdout",
        fake_connect_stdin_stdout,
    )

    await stdio_server.StdioServerController().run(callback)

    assert isinstance(captured["connection"], StdioConnection)


async def test_websocket_client_controller_invokes_connection_callback(monkeypatch):
    captured = {}
    websocket = FakeWebSocket()

    def fake_connect(url, open_timeout, proxy="__unset__", **kwargs):
        captured["url"] = url
        captured["open_timeout"] = open_timeout
        captured["proxy"] = proxy
        captured.update(kwargs)
        return FakeWebSocketConnectContext(websocket)

    async def callback(connection):
        captured["connection"] = connection

    async def on_failed(controller, exc):
        captured["failure"] = (controller, exc)

    monkeypatch.setattr(ws_client.websockets, "connect", fake_connect)
    controller = ws_client.WebSocketClientController("ws://localhost:9000", on_failed)

    await controller.run(callback)

    assert captured["url"] == "ws://localhost:9000"
    assert captured["open_timeout"] == 10
    # Internal control-plane connections must bypass proxy auto-detection.
    assert captured["proxy"] is None
    assert isinstance(captured["connection"], WebSocketConnection)
    assert "failure" not in captured


async def test_websocket_client_controller_reports_connection_failure(monkeypatch):
    captured = {}
    error = OSError("network down")

    def fake_connect(url, open_timeout, proxy=None, **kwargs):
        raise error

    async def callback(connection):
        captured["connection"] = connection

    async def on_failed(controller, exc):
        captured["failure"] = (controller, exc)

    monkeypatch.setattr(ws_client.websockets, "connect", fake_connect)
    controller = ws_client.WebSocketClientController("ws://localhost:9000", on_failed)

    await controller.run(callback)

    assert captured["failure"] == (controller, error)
    assert "connection" not in captured


async def test_websocket_server_controller_run_waits_for_server(monkeypatch):
    fake_server = FakeServer()
    captured = {}

    async def fake_serve(handler, host, port, **kwargs):
        captured["handler"] = handler
        captured["host"] = host
        captured["port"] = port
        captured.update(kwargs)
        return fake_server

    async def callback(connection):
        captured["connection"] = connection

    monkeypatch.setattr(ws_server.websockets, "serve", fake_serve)
    controller = ws_server.WebSocketServerController(port=9000)

    await controller.run(callback)

    assert captured["handler"] == controller.handle_connection
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9000
    assert captured["process_request"] is ws_server.process_http_request
    assert captured["logger"] is ws_server.protocol_logger
    assert fake_server.waited is True
    assert fake_server.closed is True


def test_websocket_server_health_endpoint():
    connection = MagicMock()
    response = object()
    connection.respond.return_value = response

    result = ws_server.process_http_request(
        connection, SimpleNamespace(path="/healthz")
    )

    assert result is response
    connection.respond.assert_called_once_with(HTTPStatus.OK, "ok\n")


def test_websocket_server_non_health_request_continues_handshake():
    connection = MagicMock()

    result = ws_server.process_http_request(
        connection, SimpleNamespace(path="/control/ws")
    )

    assert result is None
    connection.respond.assert_not_called()


async def test_websocket_server_controller_wraps_new_connections():
    captured = {}
    controller = ws_server.WebSocketServerController(port=9000)

    async def callback(connection):
        captured["connection"] = connection

    controller._new_connection_callback = callback

    await controller.handle_connection(FakeWebSocket())

    assert isinstance(captured["connection"], WebSocketConnection)
