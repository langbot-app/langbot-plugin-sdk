"""Unit tests for langbot_plugin.box.server.

These tests exercise the box action RPC server WITHOUT a live aiohttp
server. ``BoxServerHandler`` is instantiated with a mock ``Connection`` and a
mock ``BoxRuntime``; the registered action handlers are then invoked directly
via ``handler.actions[...]`` and the resulting ``ActionResponse`` objects are
asserted. The pure helpers, the ``AiohttpWSConnection`` adapter and the
error/early-return paths of the aiohttp request handlers are also covered with
``unittest.mock``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest
from aiohttp import web

from langbot_plugin.box import server
from langbot_plugin.box.actions import LangBotToBoxAction
from langbot_plugin.box.errors import (
    BoxManagedProcessConflictError,
    BoxManagedProcessNotFoundError,
    BoxSessionNotFoundError,
)
from langbot_plugin.box.models import (
    BoxExecutionResult,
    BoxExecutionStatus,
)
from langbot_plugin.box.server import (
    AiohttpWSConnection,
    BoxServerHandler,
    _error_response,
    _result_to_dict,
    create_app,
    create_ws_relay_app,
    handle_managed_process_ws,
    handle_rpc_ws,
)
from langbot_plugin.entities.io.actions.enums import CommonAction
from langbot_plugin.entities.io.errors import ConnectionClosedError
from langbot_plugin.entities.io.resp import ActionResponse


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_connection():
    """A mock Connection (send/receive/close are awaitables)."""
    conn = mock.MagicMock()
    conn.send = mock.AsyncMock()
    conn.receive = mock.AsyncMock()
    conn.close = mock.AsyncMock()
    return conn


@pytest.fixture
def mock_runtime():
    """A mock BoxRuntime with async/sync methods stubbed out.

    Async methods are AsyncMock; the skill_store and synchronous methods are
    plain MagicMock. Defaults return realistic shapes; individual tests
    override return values / side effects as needed.
    """
    runtime = mock.MagicMock()

    runtime.get_backend_info = mock.AsyncMock(
        return_value={"name": "docker", "available": True}
    )
    runtime.get_status = mock.AsyncMock(
        return_value={
            "backend": {"name": "docker", "available": True},
            "active_sessions": 0,
            "managed_processes": 0,
            "session_ttl_sec": 300,
        }
    )
    runtime.execute = mock.AsyncMock()
    runtime.create_session = mock.AsyncMock(return_value={"session_id": "s1"})
    runtime.get_session = mock.MagicMock(return_value={"session_id": "s1"})
    runtime.get_sessions = mock.MagicMock(return_value=[{"session_id": "s1"}])
    runtime.delete_session = mock.AsyncMock()
    runtime.start_managed_process = mock.AsyncMock(
        return_value={"process_id": "default", "status": "running"}
    )
    runtime.get_managed_process = mock.MagicMock(
        return_value={"process_id": "default", "status": "running"}
    )
    runtime.stop_managed_process = mock.AsyncMock()
    runtime.init = mock.MagicMock()
    runtime.shutdown = mock.AsyncMock()

    skill_store = mock.MagicMock()
    skill_store.list_skills = mock.MagicMock(return_value=[{"name": "demo"}])
    skill_store.get_skill = mock.MagicMock(return_value={"name": "demo"})
    skill_store.create_skill = mock.MagicMock(return_value={"name": "demo"})
    skill_store.update_skill = mock.MagicMock(return_value={"name": "demo"})
    skill_store.delete_skill = mock.MagicMock(return_value={"deleted": True})
    skill_store.scan_directory = mock.MagicMock(return_value={"name": "demo"})
    skill_store.list_skill_files = mock.MagicMock(return_value={"entries": []})
    skill_store.read_skill_file = mock.MagicMock(return_value={"content": "x"})
    skill_store.write_skill_file = mock.MagicMock(return_value={"written": True})
    skill_store.preview_zip_upload = mock.MagicMock(return_value=[{"name": "demo"}])
    skill_store.install_zip_upload = mock.MagicMock(return_value=[{"name": "demo"}])
    runtime.skill_store = skill_store

    return runtime


@pytest.fixture
def handler(mock_connection, mock_runtime):
    return BoxServerHandler(mock_connection, mock_runtime)


def _spec_data(**overrides) -> dict:
    """A valid BoxSpec payload."""
    data = {"session_id": "s1", "cmd": "echo hi"}
    data.update(overrides)
    return data


async def _invoke(handler: BoxServerHandler, action, data: dict) -> ActionResponse:
    """Invoke a registered action handler by its enum and return the response."""
    func = handler.actions[action.value]
    return await func(data)


# ── Pure helpers ─────────────────────────────────────────────────────


def test_result_to_dict_serializes_execution_result():
    result = BoxExecutionResult(
        session_id="s1",
        backend_name="docker",
        status=BoxExecutionStatus.COMPLETED,
        exit_code=0,
        stdout="out",
        stderr="",
        duration_ms=12,
    )
    as_dict = _result_to_dict(result)
    assert as_dict["session_id"] == "s1"
    assert as_dict["status"] == "completed"  # enum serialized to its value
    assert as_dict["exit_code"] == 0
    assert as_dict["duration_ms"] == 12


def test_error_response_shape_and_status():
    resp = _error_response(BoxSessionNotFoundError("nope"))
    assert isinstance(resp, web.Response)
    assert resp.status == 400
    body = resp.text
    assert "BoxSessionNotFoundError" in body
    assert "nope" in body


# ── AiohttpWSConnection adapter ──────────────────────────────────────


async def test_ws_connection_send_delegates_to_ws():
    ws = mock.MagicMock()
    ws.send_str = mock.AsyncMock()
    conn = AiohttpWSConnection(ws)
    await conn.send("hello")
    ws.send_str.assert_awaited_once_with("hello")


async def test_ws_connection_send_raises_connection_closed_on_reset():
    ws = mock.MagicMock()
    ws.send_str = mock.AsyncMock(side_effect=ConnectionResetError())
    conn = AiohttpWSConnection(ws)
    with pytest.raises(ConnectionClosedError):
        await conn.send("hello")


async def test_ws_connection_receive_returns_text():
    msg = SimpleNamespace(type=web.WSMsgType.TEXT, data="payload")
    ws = mock.MagicMock()
    ws.receive = mock.AsyncMock(return_value=msg)
    conn = AiohttpWSConnection(ws)
    assert await conn.receive() == "payload"


@pytest.mark.parametrize(
    "msg_type",
    [
        web.WSMsgType.CLOSE,
        web.WSMsgType.CLOSING,
        web.WSMsgType.CLOSED,
        web.WSMsgType.ERROR,
    ],
)
async def test_ws_connection_receive_raises_on_close_types(msg_type):
    msg = SimpleNamespace(type=msg_type, data=None)
    ws = mock.MagicMock()
    ws.receive = mock.AsyncMock(return_value=msg)
    conn = AiohttpWSConnection(ws)
    with pytest.raises(ConnectionClosedError, match="Connection closed"):
        await conn.receive()


async def test_ws_connection_receive_raises_on_unexpected_type():
    msg = SimpleNamespace(type=web.WSMsgType.BINARY, data=b"x")
    ws = mock.MagicMock()
    ws.receive = mock.AsyncMock(return_value=msg)
    conn = AiohttpWSConnection(ws)
    with pytest.raises(ConnectionClosedError, match="Unexpected message type"):
        await conn.receive()


async def test_ws_connection_close_delegates():
    ws = mock.MagicMock()
    ws.close = mock.AsyncMock()
    conn = AiohttpWSConnection(ws)
    await conn.close()
    ws.close.assert_awaited_once()


# ── Handler construction / registration ──────────────────────────────


def test_handler_registers_all_box_actions(handler):
    # Every box action is registered.
    for action in LangBotToBoxAction:
        assert action.value in handler.actions
    # Plus the common PING action registered by the box handler.
    assert CommonAction.PING.value in handler.actions
    # Plus FILE_CHUNK registered by the base Handler.
    assert CommonAction.FILE_CHUNK.value in handler.actions


def test_handler_keeps_runtime_reference(mock_connection, mock_runtime):
    h = BoxServerHandler(mock_connection, mock_runtime)
    assert h._runtime is mock_runtime
    assert h.conn is mock_connection
    assert h.name == "BoxServerHandler"


# ── PING / HEALTH / STATUS / GET_BACKEND_INFO ────────────────────────


async def test_ping(handler):
    resp = await _invoke(handler, CommonAction.PING, {})
    assert resp.code == 0
    assert resp.data == {}


async def test_health(handler, mock_runtime):
    resp = await _invoke(handler, LangBotToBoxAction.HEALTH, {})
    assert resp.code == 0
    assert resp.data == {"name": "docker", "available": True}
    mock_runtime.get_backend_info.assert_awaited_once()


async def test_status(handler, mock_runtime):
    resp = await _invoke(handler, LangBotToBoxAction.STATUS, {})
    assert resp.code == 0
    assert resp.data["active_sessions"] == 0
    mock_runtime.get_status.assert_awaited_once()


async def test_get_backend_info(handler, mock_runtime):
    resp = await _invoke(handler, LangBotToBoxAction.GET_BACKEND_INFO, {})
    assert resp.code == 0
    assert resp.data == {"name": "docker", "available": True}
    mock_runtime.get_backend_info.assert_awaited_once()


# ── EXEC ─────────────────────────────────────────────────────────────


async def test_exec_success(handler, mock_runtime):
    result = BoxExecutionResult(
        session_id="s1",
        backend_name="docker",
        status=BoxExecutionStatus.COMPLETED,
        exit_code=0,
        stdout="hi\n",
        stderr="",
        duration_ms=5,
    )
    mock_runtime.execute.return_value = result

    resp = await _invoke(handler, LangBotToBoxAction.EXEC, _spec_data())

    assert resp.code == 0
    assert resp.data["stdout"] == "hi\n"
    assert resp.data["status"] == "completed"
    # runtime.execute was called with a validated BoxSpec.
    mock_runtime.execute.assert_awaited_once()
    (spec_arg,), _ = mock_runtime.execute.call_args
    assert spec_arg.session_id == "s1"
    assert spec_arg.cmd == "echo hi"


async def test_exec_invalid_spec_returns_validation_error(handler, mock_runtime):
    # Missing required session_id triggers a pydantic ValidationError.
    resp = await _invoke(handler, LangBotToBoxAction.EXEC, {"cmd": "echo hi"})
    assert resp.code == 1
    assert "BoxValidationError" in resp.message
    mock_runtime.execute.assert_not_awaited()


# ── CREATE_SESSION ───────────────────────────────────────────────────


async def test_create_session_success(handler, mock_runtime):
    mock_runtime.create_session.return_value = {"session_id": "s1", "image": "img"}
    resp = await _invoke(handler, LangBotToBoxAction.CREATE_SESSION, _spec_data())
    assert resp.code == 0
    assert resp.data["session_id"] == "s1"
    mock_runtime.create_session.assert_awaited_once()


async def test_create_session_invalid_spec(handler, mock_runtime):
    resp = await _invoke(
        handler, LangBotToBoxAction.CREATE_SESSION, {"cmd": "echo hi"}
    )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message
    mock_runtime.create_session.assert_not_awaited()


# ── GET_SESSION / GET_SESSIONS / DELETE_SESSION ──────────────────────


async def test_get_session(handler, mock_runtime):
    mock_runtime.get_session.return_value = {"session_id": "abc"}
    resp = await _invoke(
        handler, LangBotToBoxAction.GET_SESSION, {"session_id": "abc"}
    )
    assert resp.code == 0
    assert resp.data == {"session_id": "abc"}
    mock_runtime.get_session.assert_called_once_with("abc")


async def test_get_sessions_wraps_list(handler, mock_runtime):
    mock_runtime.get_sessions.return_value = [{"session_id": "a"}, {"session_id": "b"}]
    resp = await _invoke(handler, LangBotToBoxAction.GET_SESSIONS, {})
    assert resp.code == 0
    assert resp.data == {"sessions": [{"session_id": "a"}, {"session_id": "b"}]}


async def test_delete_session(handler, mock_runtime):
    resp = await _invoke(
        handler, LangBotToBoxAction.DELETE_SESSION, {"session_id": "gone"}
    )
    assert resp.code == 0
    assert resp.data == {"deleted": "gone"}
    mock_runtime.delete_session.assert_awaited_once_with("gone")


# ── MANAGED PROCESS ──────────────────────────────────────────────────


async def test_start_managed_process_success(handler, mock_runtime):
    mock_runtime.start_managed_process.return_value = {
        "process_id": "p1",
        "status": "running",
    }
    data = {
        "session_id": "s1",
        "spec": {"process_id": "p1", "command": "python", "args": ["-V"]},
    }
    resp = await _invoke(handler, LangBotToBoxAction.START_MANAGED_PROCESS, data)
    assert resp.code == 0
    assert resp.data["process_id"] == "p1"
    mock_runtime.start_managed_process.assert_awaited_once()
    (session_id, spec_arg), _ = mock_runtime.start_managed_process.call_args
    assert session_id == "s1"
    assert spec_arg.command == "python"
    assert spec_arg.process_id == "p1"


async def test_start_managed_process_invalid_spec(handler, mock_runtime):
    # Empty command fails BoxManagedProcessSpec validation.
    data = {"session_id": "s1", "spec": {"command": ""}}
    resp = await _invoke(handler, LangBotToBoxAction.START_MANAGED_PROCESS, data)
    assert resp.code == 1
    assert "BoxValidationError" in resp.message
    mock_runtime.start_managed_process.assert_not_awaited()


async def test_get_managed_process_defaults_process_id(handler, mock_runtime):
    resp = await _invoke(
        handler, LangBotToBoxAction.GET_MANAGED_PROCESS, {"session_id": "s1"}
    )
    assert resp.code == 0
    mock_runtime.get_managed_process.assert_called_once_with("s1", "default")


async def test_get_managed_process_explicit_process_id(handler, mock_runtime):
    await _invoke(
        handler,
        LangBotToBoxAction.GET_MANAGED_PROCESS,
        {"session_id": "s1", "process_id": "p2"},
    )
    mock_runtime.get_managed_process.assert_called_once_with("s1", "p2")


async def test_stop_managed_process_default(handler, mock_runtime):
    resp = await _invoke(
        handler, LangBotToBoxAction.STOP_MANAGED_PROCESS, {"session_id": "s1"}
    )
    assert resp.code == 0
    assert resp.data == {"stopped": "default"}
    mock_runtime.stop_managed_process.assert_awaited_once_with("s1", "default")


async def test_stop_managed_process_explicit(handler, mock_runtime):
    resp = await _invoke(
        handler,
        LangBotToBoxAction.STOP_MANAGED_PROCESS,
        {"session_id": "s1", "process_id": "p3"},
    )
    assert resp.data == {"stopped": "p3"}
    mock_runtime.stop_managed_process.assert_awaited_once_with("s1", "p3")


# ── SKILL store actions (sync skill_store) ───────────────────────────


async def test_list_skills(handler, mock_runtime):
    resp = await _invoke(handler, LangBotToBoxAction.LIST_SKILLS, {})
    assert resp.code == 0
    assert resp.data == {"skills": [{"name": "demo"}]}
    mock_runtime.skill_store.list_skills.assert_called_once()


async def test_get_skill(handler, mock_runtime):
    resp = await _invoke(handler, LangBotToBoxAction.GET_SKILL, {"name": "demo"})
    assert resp.code == 0
    assert resp.data == {"skill": {"name": "demo"}}
    mock_runtime.skill_store.get_skill.assert_called_once_with("demo")


async def test_create_skill_success(handler, mock_runtime):
    resp = await _invoke(
        handler, LangBotToBoxAction.CREATE_SKILL, {"skill": {"name": "demo"}}
    )
    assert resp.code == 0
    assert resp.data == {"skill": {"name": "demo"}}
    mock_runtime.skill_store.create_skill.assert_called_once_with({"name": "demo"})


async def test_create_skill_error(handler, mock_runtime):
    mock_runtime.skill_store.create_skill.side_effect = ValueError("bad skill")
    resp = await _invoke(
        handler, LangBotToBoxAction.CREATE_SKILL, {"skill": {"name": "demo"}}
    )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message
    assert "bad skill" in resp.message


async def test_update_skill_success(handler, mock_runtime):
    resp = await _invoke(
        handler,
        LangBotToBoxAction.UPDATE_SKILL,
        {"name": "demo", "skill": {"name": "demo2"}},
    )
    assert resp.code == 0
    mock_runtime.skill_store.update_skill.assert_called_once_with(
        "demo", {"name": "demo2"}
    )


async def test_update_skill_error(handler, mock_runtime):
    mock_runtime.skill_store.update_skill.side_effect = KeyError("missing")
    resp = await _invoke(
        handler,
        LangBotToBoxAction.UPDATE_SKILL,
        {"name": "demo", "skill": {}},
    )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message


async def test_delete_skill_success(handler, mock_runtime):
    resp = await _invoke(
        handler, LangBotToBoxAction.DELETE_SKILL, {"name": "demo"}
    )
    assert resp.code == 0
    assert resp.data == {"deleted": True}
    mock_runtime.skill_store.delete_skill.assert_called_once_with("demo")


async def test_delete_skill_error(handler, mock_runtime):
    mock_runtime.skill_store.delete_skill.side_effect = RuntimeError("locked")
    resp = await _invoke(
        handler, LangBotToBoxAction.DELETE_SKILL, {"name": "demo"}
    )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message


async def test_scan_skill_directory_success(handler, mock_runtime):
    resp = await _invoke(
        handler, LangBotToBoxAction.SCAN_SKILL_DIRECTORY, {"path": "/skills/demo"}
    )
    assert resp.code == 0
    assert resp.data == {"name": "demo"}
    mock_runtime.skill_store.scan_directory.assert_called_once_with("/skills/demo")


async def test_scan_skill_directory_error(handler, mock_runtime):
    mock_runtime.skill_store.scan_directory.side_effect = FileNotFoundError("nope")
    resp = await _invoke(
        handler, LangBotToBoxAction.SCAN_SKILL_DIRECTORY, {"path": "/x"}
    )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message


async def test_list_skill_files_uses_defaults(handler, mock_runtime):
    resp = await _invoke(
        handler, LangBotToBoxAction.LIST_SKILL_FILES, {"name": "demo"}
    )
    assert resp.code == 0
    mock_runtime.skill_store.list_skill_files.assert_called_once_with(
        "demo", ".", include_hidden=False, max_entries=200
    )


async def test_list_skill_files_passes_overrides(handler, mock_runtime):
    await _invoke(
        handler,
        LangBotToBoxAction.LIST_SKILL_FILES,
        {
            "name": "demo",
            "path": "sub",
            "include_hidden": True,
            "max_entries": 5,
        },
    )
    mock_runtime.skill_store.list_skill_files.assert_called_once_with(
        "demo", "sub", include_hidden=True, max_entries=5
    )


async def test_list_skill_files_error(handler, mock_runtime):
    mock_runtime.skill_store.list_skill_files.side_effect = ValueError("nope")
    resp = await _invoke(
        handler, LangBotToBoxAction.LIST_SKILL_FILES, {"name": "demo"}
    )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message


async def test_read_skill_file_success(handler, mock_runtime):
    resp = await _invoke(
        handler,
        LangBotToBoxAction.READ_SKILL_FILE,
        {"name": "demo", "path": "notes.txt"},
    )
    assert resp.code == 0
    assert resp.data == {"content": "x"}
    mock_runtime.skill_store.read_skill_file.assert_called_once_with(
        "demo", "notes.txt"
    )


async def test_read_skill_file_error(handler, mock_runtime):
    mock_runtime.skill_store.read_skill_file.side_effect = ValueError("nope")
    resp = await _invoke(
        handler,
        LangBotToBoxAction.READ_SKILL_FILE,
        {"name": "demo", "path": "x"},
    )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message


async def test_write_skill_file_success(handler, mock_runtime):
    resp = await _invoke(
        handler,
        LangBotToBoxAction.WRITE_SKILL_FILE,
        {"name": "demo", "path": "notes.txt", "content": "hi"},
    )
    assert resp.code == 0
    assert resp.data == {"written": True}
    mock_runtime.skill_store.write_skill_file.assert_called_once_with(
        "demo", "notes.txt", "hi"
    )


async def test_write_skill_file_defaults_content(handler, mock_runtime):
    await _invoke(
        handler,
        LangBotToBoxAction.WRITE_SKILL_FILE,
        {"name": "demo", "path": "notes.txt"},
    )
    mock_runtime.skill_store.write_skill_file.assert_called_once_with(
        "demo", "notes.txt", ""
    )


async def test_write_skill_file_error(handler, mock_runtime):
    mock_runtime.skill_store.write_skill_file.side_effect = OSError("disk full")
    resp = await _invoke(
        handler,
        LangBotToBoxAction.WRITE_SKILL_FILE,
        {"name": "demo", "path": "x"},
    )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message


# ── PREVIEW / INSTALL skill zip (use Handler file helpers) ───────────


async def test_preview_skill_zip_reads_and_deletes_local_file(handler, mock_runtime):
    with (
        mock.patch.object(
            handler, "read_local_file", mock.AsyncMock(return_value=b"zipbytes")
        ) as read_mock,
        mock.patch.object(
            handler, "delete_local_file", mock.AsyncMock()
        ) as delete_mock,
    ):
        resp = await _invoke(
            handler,
            LangBotToBoxAction.PREVIEW_SKILL_ZIP,
            {"file_key": "key1", "filename": "demo.zip", "source_subdir": "pkgs"},
        )

    assert resp.code == 0
    assert resp.data == {"skills": [{"name": "demo"}]}
    read_mock.assert_awaited_once_with("key1")
    delete_mock.assert_awaited_once_with("key1")
    mock_runtime.skill_store.preview_zip_upload.assert_called_once_with(
        file_bytes=b"zipbytes",
        filename="demo.zip",
        source_subdir="pkgs",
        target_suffix="upload",
    )


async def test_preview_skill_zip_error(handler, mock_runtime):
    mock_runtime.skill_store.preview_zip_upload.side_effect = ValueError("bad zip")
    with (
        mock.patch.object(
            handler, "read_local_file", mock.AsyncMock(return_value=b"x")
        ),
        mock.patch.object(handler, "delete_local_file", mock.AsyncMock()),
    ):
        resp = await _invoke(
            handler,
            LangBotToBoxAction.PREVIEW_SKILL_ZIP,
            {"file_key": "key1"},
        )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message


async def test_install_skill_zip_passes_all_args(handler, mock_runtime):
    with (
        mock.patch.object(
            handler, "read_local_file", mock.AsyncMock(return_value=b"zipbytes")
        ),
        mock.patch.object(handler, "delete_local_file", mock.AsyncMock()),
    ):
        resp = await _invoke(
            handler,
            LangBotToBoxAction.INSTALL_SKILL_ZIP,
            {
                "file_key": "key1",
                "filename": "demo.zip",
                "source_paths": ["alpha"],
                "source_path": "alpha",
                "source_subdir": "pkgs",
                "target_suffix": "v2",
            },
        )
    assert resp.code == 0
    assert resp.data == {"skills": [{"name": "demo"}]}
    mock_runtime.skill_store.install_zip_upload.assert_called_once_with(
        file_bytes=b"zipbytes",
        filename="demo.zip",
        source_paths=["alpha"],
        source_path="alpha",
        source_subdir="pkgs",
        target_suffix="v2",
    )


async def test_install_skill_zip_error(handler, mock_runtime):
    mock_runtime.skill_store.install_zip_upload.side_effect = RuntimeError("boom")
    with (
        mock.patch.object(
            handler, "read_local_file", mock.AsyncMock(return_value=b"x")
        ),
        mock.patch.object(handler, "delete_local_file", mock.AsyncMock()),
    ):
        resp = await _invoke(
            handler,
            LangBotToBoxAction.INSTALL_SKILL_ZIP,
            {"file_key": "key1"},
        )
    assert resp.code == 1
    assert "BoxValidationError" in resp.message


# ── INIT / SHUTDOWN ──────────────────────────────────────────────────


async def test_init(handler, mock_runtime):
    config = {"backend": "docker"}
    resp = await _invoke(handler, LangBotToBoxAction.INIT, config)
    assert resp.code == 0
    assert resp.data == {"initialized": True}
    mock_runtime.init.assert_called_once_with(config)


async def test_shutdown(handler, mock_runtime):
    resp = await _invoke(handler, LangBotToBoxAction.SHUTDOWN, {})
    assert resp.code == 0
    assert resp.data == {}
    mock_runtime.shutdown.assert_awaited_once()


# ── App factory ──────────────────────────────────────────────────────


def test_create_app_registers_routes_and_runtime(mock_runtime):
    app = create_app(mock_runtime)
    assert isinstance(app, web.Application)
    assert app["runtime"] is mock_runtime

    routes = {
        (route.method, route.resource.canonical)
        for route in app.router.routes()
    }
    assert ("GET", "/rpc/ws") in routes
    assert (
        "GET",
        "/v1/sessions/{session_id}/managed-process/{process_id}/ws",
    ) in routes
    assert (
        "GET",
        "/v1/sessions/{session_id}/managed-process/ws",
    ) in routes


def test_create_ws_relay_app_is_alias(mock_runtime):
    app = create_ws_relay_app(mock_runtime)
    assert isinstance(app, web.Application)
    assert app["runtime"] is mock_runtime


# ── handle_rpc_ws ────────────────────────────────────────────────────


async def test_handle_rpc_ws_prepares_ws_and_runs_handler(mock_runtime):
    fake_ws = mock.MagicMock()
    fake_ws.prepare = mock.AsyncMock()

    request = mock.MagicMock()
    request.app = {"runtime": mock_runtime}

    run_mock = mock.AsyncMock()
    with (
        mock.patch.object(server.web, "WebSocketResponse", return_value=fake_ws),
        mock.patch.object(BoxServerHandler, "run", run_mock),
    ):
        result = await handle_rpc_ws(request)

    assert result is fake_ws
    fake_ws.prepare.assert_awaited_once_with(request)
    run_mock.assert_awaited_once()


# ── handle_managed_process_ws error/early-return paths ───────────────


def _ws_request(runtime, session_id="s1", process_id=None):
    request = mock.MagicMock()
    request.app = {"runtime": runtime}
    match_info = {"session_id": session_id}
    if process_id is not None:
        match_info["process_id"] = process_id
    # match_info.get used in source; emulate dict.get default behavior.
    request.match_info = match_info
    return request


async def test_managed_process_ws_session_not_found(mock_runtime):
    mock_runtime._sessions = {}
    request = _ws_request(mock_runtime, session_id="missing")
    resp = await handle_managed_process_ws(request)
    assert isinstance(resp, web.Response)
    assert resp.status == 400
    assert "BoxSessionNotFoundError" in resp.text


async def test_managed_process_ws_process_not_found(mock_runtime):
    runtime_session = mock.MagicMock()
    runtime_session.managed_processes = {}
    mock_runtime._sessions = {"s1": runtime_session}
    request = _ws_request(mock_runtime, session_id="s1", process_id="p1")
    resp = await handle_managed_process_ws(request)
    assert isinstance(resp, web.Response)
    assert resp.status == 400
    assert "BoxManagedProcessNotFoundError" in resp.text


async def test_managed_process_ws_process_not_running(mock_runtime):
    managed = mock.MagicMock()
    managed.is_running = False
    runtime_session = mock.MagicMock()
    runtime_session.managed_processes = {"default": managed}
    mock_runtime._sessions = {"s1": runtime_session}
    request = _ws_request(mock_runtime, session_id="s1", process_id="default")
    resp = await handle_managed_process_ws(request)
    assert isinstance(resp, web.Response)
    assert resp.status == 400
    assert "BoxManagedProcessConflictError" in resp.text


async def test_managed_process_ws_stdio_unavailable_closes_ws(mock_runtime):
    # A running process whose stdio is unavailable -> ws closed with message.
    process = SimpleNamespace(stdout=None, stdin=None)
    managed = mock.MagicMock()
    managed.is_running = True
    managed.process = process
    # Real asyncio.Lock so `async with managed_process.attach_lock` works.
    managed.attach_lock = asyncio.Lock()

    runtime_session = mock.MagicMock()
    runtime_session.managed_processes = {"default": managed}
    mock_runtime._sessions = {"s1": runtime_session}

    fake_ws = mock.MagicMock()
    fake_ws.prepare = mock.AsyncMock()
    fake_ws.close = mock.AsyncMock()

    request = _ws_request(mock_runtime, session_id="s1", process_id="default")
    with mock.patch.object(server.web, "WebSocketResponse", return_value=fake_ws):
        result = await handle_managed_process_ws(request)

    assert result is fake_ws
    fake_ws.prepare.assert_awaited_once_with(request)
    fake_ws.close.assert_awaited_once()


# ── Sanity: error classes used by the relay are importable/usable ────


def test_relay_error_classes_render():
    for exc in (
        BoxSessionNotFoundError("a"),
        BoxManagedProcessNotFoundError("b"),
        BoxManagedProcessConflictError("c"),
    ):
        resp = _error_response(exc)
        assert resp.status == 400
