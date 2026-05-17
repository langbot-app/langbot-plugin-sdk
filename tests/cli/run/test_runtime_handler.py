from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.page import Page, PageRequest
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.cli.run.handler import PluginRuntimeHandler, _resolve_asset_path
from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction

from tests.helpers.protocol import ProtocolConnection, ProtocolSession


class FakeManifest:
    def __init__(self, kind: str = "Plugin", name: str = "demo"):
        self.kind = kind
        self.metadata = SimpleNamespace(name=name)
        self.icon_rel_path = None

    def model_dump(self, **kwargs):
        return {
            "kind": self.kind,
            "metadata": {"name": self.metadata.name},
        }


class FakePluginContainer:
    def __init__(self):
        self.manifest = FakeManifest()
        self.components = []

    def model_dump(self, **kwargs):
        return {
            "manifest": self.manifest.model_dump(),
            "components": [
                component.manifest.model_dump() for component in self.components
            ],
        }


class FakeComponentContainer:
    def __init__(self, kind: str, name: str, component_instance):
        self.manifest = FakeManifest(kind=kind, name=name)
        self.component_instance = component_instance


class FakePage(Page):
    def __init__(self):
        self.requests = []

    async def handle_api(self, request: PageRequest):
        self.requests.append(request)
        return {"endpoint": request.endpoint, "body": request.body}


class FakeTool(Tool):
    def __init__(self):
        self.calls = []

    async def call(self, params, session, query_id):
        self.calls.append((params, session, query_id))
        return {"ok": True, "sender_id": session.sender_id, "query_id": query_id}


def _handler():
    initialized = []

    async def initialize(plugin_settings):
        initialized.append(plugin_settings)

    handler = PluginRuntimeHandler(ProtocolConnection(), initialize)
    handler.plugin_container = FakePluginContainer()
    return handler, initialized


def test_resolve_asset_path_accepts_assets_and_component_page_files(tmp_path, monkeypatch):
    assets_file = tmp_path / "assets" / "icon.svg"
    page_file = tmp_path / "components" / "pages" / "settings.html"
    outside_file = tmp_path / "components" / "tools" / "secret.txt"
    assets_file.parent.mkdir()
    page_file.parent.mkdir(parents=True)
    outside_file.parent.mkdir(parents=True)
    assets_file.write_text("icon", encoding="utf-8")
    page_file.write_text("page", encoding="utf-8")
    outside_file.write_text("secret", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert _resolve_asset_path("icon.svg") == assets_file.resolve()
    assert _resolve_asset_path("components/pages/settings.html") == page_file.resolve()
    assert _resolve_asset_path("components/tools/secret.txt") is None
    assert _resolve_asset_path(str(assets_file.resolve())) is None


async def test_plugin_runtime_handler_initializes_plugin_and_returns_container():
    handler, initialized = _handler()

    async with ProtocolSession(handler) as session:
        initialized_response = await session.request(
            RuntimeToPluginAction.INITIALIZE_PLUGIN.value,
            {"plugin_settings": {"enabled": True}},
            seq_id=1,
        )
        container_response = await session.request(
            RuntimeToPluginAction.GET_PLUGIN_CONTAINER.value,
            seq_id=2,
        )

    assert initialized_response["code"] == 0
    assert initialized == [{"enabled": True}]
    assert container_response["data"] == {
        "manifest": {"kind": "Plugin", "metadata": {"name": "demo"}},
        "components": [],
    }


async def test_plugin_runtime_handler_icon_without_icon_path_returns_empty_payload():
    handler, _initialized = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(RuntimeToPluginAction.GET_PLUGIN_ICON.value)

    assert response["data"] == {"plugin_icon_file_key": "", "mime_type": ""}


async def test_plugin_runtime_handler_sends_readme_file_key(tmp_path, monkeypatch):
    handler, _initialized = _handler()
    (tmp_path / "readme").mkdir()
    (tmp_path / "readme" / "README_zh.md").write_bytes(b"zh readme")
    monkeypatch.chdir(tmp_path)
    sent = []

    async def fake_send_file(file_bytes, extension):
        sent.append((file_bytes, extension))
        return "readme-key"

    monkeypatch.setattr(handler, "send_file", fake_send_file)

    async with ProtocolSession(handler) as session:
        response = await session.request(
            RuntimeToPluginAction.GET_PLUGIN_README.value,
            {"language": "zh"},
        )

    assert sent == [(b"zh readme", "md")]
    assert response["data"] == {
        "plugin_readme_file_key": "readme-key",
        "mime_type": "text/markdown",
    }


async def test_plugin_runtime_handler_get_assets_file_rejects_path_traversal(
    tmp_path,
    monkeypatch,
):
    handler, _initialized = _handler()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    async with ProtocolSession(handler) as session:
        response = await session.request(
            RuntimeToPluginAction.GET_PLUGIN_ASSETS_FILE.value,
            {"file_key": "../secret.txt"},
        )

    assert response["data"] == {"file_file_key": None, "mime_type": None}


async def test_plugin_runtime_handler_get_assets_file_sends_allowed_asset(
    tmp_path,
    monkeypatch,
):
    handler, _initialized = _handler()
    asset = tmp_path / "assets" / "config.json"
    asset.parent.mkdir()
    asset.write_bytes(b'{"ok": true}')
    monkeypatch.chdir(tmp_path)
    sent = []

    async def fake_send_file(file_bytes, extension):
        sent.append((file_bytes, extension))
        return "asset-key"

    monkeypatch.setattr(handler, "send_file", fake_send_file)

    async with ProtocolSession(handler) as session:
        response = await session.request(
            RuntimeToPluginAction.GET_PLUGIN_ASSETS_FILE.value,
            {"file_key": "config.json"},
        )

    assert sent == [(b'{"ok": true}', "")]
    assert response["data"] == {
        "file_file_key": "asset-key",
        "mime_type": "application/json",
    }


async def test_plugin_runtime_handler_page_api_reports_missing_and_uninitialized_page():
    handler, _initialized = _handler()
    handler.plugin_container.components = [
        FakeComponentContainer(Page.__kind__, "settings", NoneComponent())
    ]

    async with ProtocolSession(handler) as session:
        missing_page_id = await session.request(
            RuntimeToPluginAction.PAGE_API.value,
            {},
            seq_id=1,
        )
        uninitialized = await session.request(
            RuntimeToPluginAction.PAGE_API.value,
            {"page_id": "settings"},
            seq_id=2,
        )
        missing = await session.request(
            RuntimeToPluginAction.PAGE_API.value,
            {"page_id": "missing"},
            seq_id=3,
        )

    assert missing_page_id["data"] == {
        "data": None,
        "error": "page_id is required",
    }
    assert uninitialized["data"] == {
        "data": None,
        "error": "Page component is not initialized",
    }
    assert missing["data"] == {"data": None, "error": "Page 'missing' not found"}


async def test_plugin_runtime_handler_page_api_invokes_page_component():
    handler, _initialized = _handler()
    page = FakePage()
    handler.plugin_container.components = [
        FakeComponentContainer(Page.__kind__, "settings", page)
    ]

    async with ProtocolSession(handler) as session:
        response = await session.request(
            RuntimeToPluginAction.PAGE_API.value,
            {
                "page_id": "settings",
                "endpoint": "/save",
                "method": "PUT",
                "body": {"enabled": True},
            },
        )

    assert response["data"] == {
        "data": {"endpoint": "/save", "body": {"enabled": True}},
        "error": None,
    }
    assert page.requests[0].method == "PUT"


async def test_plugin_runtime_handler_call_tool_invokes_matching_tool_component():
    handler, _initialized = _handler()
    tool = FakeTool()
    handler.plugin_container.components = [
        FakeComponentContainer(Tool.__kind__, "weather", tool)
    ]

    async with ProtocolSession(handler) as session:
        response = await session.request(
            RuntimeToPluginAction.CALL_TOOL.value,
            {
                "tool_name": "weather",
                "tool_parameters": {"city": "Shanghai"},
                "session": {
                    "launcher_type": "person",
                    "launcher_id": "launcher",
                    "sender_id": "sender",
                },
                "query_id": 7,
            },
        )

    assert response["data"] == {
        "tool_response": {"ok": True, "sender_id": "sender", "query_id": 7}
    }
    assert tool.calls[0][0] == {"city": "Shanghai"}


async def test_plugin_runtime_handler_call_tool_reports_missing_or_uninitialized_tool():
    handler, _initialized = _handler()
    handler.plugin_container.components = [
        FakeComponentContainer(Tool.__kind__, "weather", NoneComponent())
    ]

    async with ProtocolSession(handler) as session:
        uninitialized = await session.request(
            RuntimeToPluginAction.CALL_TOOL.value,
            {
                "tool_name": "weather",
                "tool_parameters": {},
                "session": {
                    "launcher_type": "person",
                    "launcher_id": "launcher",
                    "sender_id": "sender",
                },
                "query_id": 1,
            },
            seq_id=1,
        )
        missing = await session.request(
            RuntimeToPluginAction.CALL_TOOL.value,
            {
                "tool_name": "missing",
                "tool_parameters": {},
                "session": {},
                "query_id": 1,
            },
            seq_id=2,
        )

    assert uninitialized["code"] == 1
    assert uninitialized["message"] == "Tool is not initialized"
    assert missing["code"] == 1
    assert missing["message"] == "Tool missing not found"


async def test_plugin_runtime_handler_shutdown_schedules_callback():
    handler, _initialized = _handler()
    called = asyncio.Event()

    async def shutdown():
        called.set()

    handler.shutdown_callback = shutdown

    async with ProtocolSession(handler) as session:
        response = await session.request(RuntimeToPluginAction.SHUTDOWN.value)
        await asyncio.wait_for(called.wait(), timeout=1)

    assert response["data"] == {}
