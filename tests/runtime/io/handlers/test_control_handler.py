from __future__ import annotations

from types import SimpleNamespace

from langbot_plugin.entities.io.actions.enums import (
    CommonAction,
    LangBotToRuntimeAction,
)
from langbot_plugin.runtime.io.handlers.control import ControlConnectionHandler

from tests.helpers.protocol import ProtocolConnection, ProtocolSession


class Dumpable:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, **kwargs):
        return self.payload


class FakePlugin:
    def __init__(self, author="tester", name="demo"):
        self.manifest = SimpleNamespace(
            metadata=SimpleNamespace(author=author, name=name)
        )

    def model_dump(self, **kwargs):
        return {"manifest": {"author": self.manifest.metadata.author, "name": self.manifest.metadata.name}}


class FakePluginManager:
    def __init__(self):
        self.plugins = [FakePlugin()]
        self.calls = []

    async def get_plugin_readme(self, author, plugin_name, language):
        self.calls.append(("get_plugin_readme", author, plugin_name, language))
        return b"# readme"

    async def get_plugin_assets_file(self, author, plugin_name, file_key):
        self.calls.append(("get_plugin_assets_file", author, plugin_name, file_key))
        return b"asset", "text/plain"

    async def handle_page_api(
        self,
        plugin_author,
        plugin_name,
        page_id,
        endpoint,
        method,
        body,
    ):
        self.calls.append(
            (
                "handle_page_api",
                plugin_author,
                plugin_name,
                page_id,
                endpoint,
                method,
                body,
            )
        )
        return {"data": {"ok": True}, "error": None}

    async def install_plugin(self, install_source, install_info):
        self.calls.append(("install_plugin", install_source.value, install_info))
        yield {"current_action": "downloaded"}
        yield {"current_action": "mounted"}

    async def restart_plugin(self, plugin_author, plugin_name):
        self.calls.append(("restart_plugin", plugin_author, plugin_name))
        yield {"current_action": "stopped"}

    async def delete_plugin(self, plugin_author, plugin_name):
        self.calls.append(("delete_plugin", plugin_author, plugin_name))
        yield {"current_action": "deleted"}

    async def list_tools(self, include_plugins=None):
        self.calls.append(("list_tools", include_plugins))
        return [Dumpable({"name": "weather"})]

    async def call_tool(
        self,
        tool_name,
        tool_parameters,
        session,
        query_id,
        include_plugins=None,
    ):
        self.calls.append(
            (
                "call_tool",
                tool_name,
                tool_parameters,
                session,
                query_id,
                include_plugins,
            )
        )
        return {"text": "sunny"}

    async def list_commands(self, include_plugins=None):
        self.calls.append(("list_commands", include_plugins))
        return [Dumpable({"name": "start"})]

    async def list_knowledge_engines(self):
        self.calls.append(("list_knowledge_engines",))
        return [{"name": "rag"}]

    async def rag_ingest_document(self, plugin_author, plugin_name, context_data):
        self.calls.append(
            ("rag_ingest_document", plugin_author, plugin_name, context_data)
        )
        return {"document_id": "doc"}

    async def list_parsers(self):
        self.calls.append(("list_parsers",))
        return [{"name": "parser"}]

    async def parse_document(self, plugin_author, plugin_name, context_data, file_bytes):
        self.calls.append(
            ("parse_document", plugin_author, plugin_name, context_data, file_bytes)
        )
        return {"text": "parsed"}


def _handler():
    manager = FakePluginManager()
    context = SimpleNamespace(plugin_mgr=manager, ws_debug_port=5401)
    handler = ControlConnectionHandler(ProtocolConnection(), context)
    return handler, manager


async def test_control_handler_ping_protocol_response():
    handler, _manager = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(CommonAction.PING.value, seq_id=10)

    assert response["seq_id"] == 10
    assert response["code"] == 0
    assert response["data"] == {"message": "pong"}


async def test_control_handler_lists_plugins_over_protocol():
    handler, _manager = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(LangBotToRuntimeAction.LIST_PLUGINS.value)

    assert response["code"] == 0
    assert response["data"] == {
        "plugins": [{"manifest": {"author": "tester", "name": "demo"}}]
    }


async def test_control_handler_get_plugin_info_returns_match_or_none():
    handler, _manager = _handler()

    async with ProtocolSession(handler) as session:
        found = await session.request(
            LangBotToRuntimeAction.GET_PLUGIN_INFO.value,
            {"author": "tester", "plugin_name": "demo"},
            seq_id=1,
        )
        missing = await session.request(
            LangBotToRuntimeAction.GET_PLUGIN_INFO.value,
            {"author": "tester", "plugin_name": "missing"},
            seq_id=2,
        )

    assert found["data"]["plugin"] == {"manifest": {"author": "tester", "name": "demo"}}
    assert missing["data"]["plugin"] is None


async def test_control_handler_get_plugin_readme_sends_file_key(monkeypatch):
    handler, manager = _handler()

    async def fake_send_file(file_bytes, extension):
        assert file_bytes == b"# readme"
        assert extension == "md"
        return "readme-key"

    monkeypatch.setattr(handler, "send_file", fake_send_file)

    async with ProtocolSession(handler) as session:
        response = await session.request(
            LangBotToRuntimeAction.GET_PLUGIN_README.value,
            {
                "plugin_author": "tester",
                "plugin_name": "demo",
                "language": "zh",
            },
        )

    assert manager.calls == [("get_plugin_readme", "tester", "demo", "zh")]
    assert response["data"] == {"readme_file_key": "readme-key"}


async def test_control_handler_get_plugin_assets_file_sends_file_key(monkeypatch):
    handler, manager = _handler()

    async def fake_send_file(file_bytes, extension):
        assert file_bytes == b"asset"
        assert extension == ""
        return "asset-key"

    monkeypatch.setattr(handler, "send_file", fake_send_file)

    async with ProtocolSession(handler) as session:
        response = await session.request(
            LangBotToRuntimeAction.GET_PLUGIN_ASSETS_FILE.value,
            {
                "plugin_author": "tester",
                "plugin_name": "demo",
                "file_path": "icon.svg",
            },
        )

    assert manager.calls == [
        ("get_plugin_assets_file", "tester", "demo", "icon.svg")
    ]
    assert response["data"] == {
        "file_file_key": "asset-key",
        "mime_type": "text/plain",
    }


async def test_control_handler_page_api_validates_required_fields():
    handler, _manager = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(
            LangBotToRuntimeAction.PAGE_API.value,
            {"plugin_author": "tester", "plugin_name": "demo"},
        )

    assert response["code"] == 0
    assert response["data"] == {
        "data": None,
        "error": "Missing required field: page_id",
    }


async def test_control_handler_page_api_delegates_to_plugin_manager():
    handler, manager = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(
            LangBotToRuntimeAction.PAGE_API.value,
            {
                "plugin_author": "tester",
                "plugin_name": "demo",
                "page_id": "settings",
                "endpoint": "/save",
                "method": "POST",
                "body": {"enabled": True},
            },
        )

    assert manager.calls == [
        (
            "handle_page_api",
            "tester",
            "demo",
            "settings",
            "/save",
            "POST",
            {"enabled": True},
        )
    ]
    assert response["data"] == {"data": {"ok": True}, "error": None}


async def test_control_handler_install_plugin_streams_progress_and_reads_local_package(
    monkeypatch,
):
    handler, manager = _handler()
    file_ops = []

    async def fake_read_local_file(file_key):
        file_ops.append(("read", file_key))
        return b"package"

    async def fake_delete_local_file(file_key):
        file_ops.append(("delete", file_key))

    monkeypatch.setattr(handler, "read_local_file", fake_read_local_file)
    monkeypatch.setattr(handler, "delete_local_file", fake_delete_local_file)

    async with ProtocolSession(handler) as session:
        responses = await session.request_messages(
            LangBotToRuntimeAction.INSTALL_PLUGIN.value,
            {
                "install_source": "local",
                "install_info": {"plugin_file_key": "pkg-key"},
            },
            count=4,
        )

    assert file_ops == [("read", "pkg-key"), ("delete", "pkg-key")]
    assert manager.calls == [
        (
            "install_plugin",
            "local",
            {"plugin_file_key": "pkg-key", "plugin_file": b"package"},
        )
    ]
    assert [response["chunk_status"] for response in responses] == [
        "continue",
        "continue",
        "continue",
        "end",
    ]
    assert [response["data"] for response in responses] == [
        {"current_action": "downloaded"},
        {"current_action": "mounted"},
        {"current_action": "plugin installed"},
        {},
    ]


async def test_control_handler_parse_document_reads_transferred_file(monkeypatch):
    handler, manager = _handler()
    file_ops = []

    async def fake_read_local_file(file_key):
        file_ops.append(("read", file_key))
        return b"document"

    async def fake_delete_local_file(file_key):
        file_ops.append(("delete", file_key))

    monkeypatch.setattr(handler, "read_local_file", fake_read_local_file)
    monkeypatch.setattr(handler, "delete_local_file", fake_delete_local_file)

    async with ProtocolSession(handler) as session:
        response = await session.request(
            LangBotToRuntimeAction.PARSE_DOCUMENT.value,
            {
                "plugin_author": "tester",
                "plugin_name": "demo",
                "context": {"file_key": "file-key", "mime_type": "text/plain"},
            },
        )

    assert file_ops == [("read", "file-key"), ("delete", "file-key")]
    assert manager.calls == [
        (
            "parse_document",
            "tester",
            "demo",
            {"mime_type": "text/plain"},
            b"document",
        )
    ]
    assert response["data"] == {"text": "parsed"}


async def test_control_handler_lists_tools_and_commands_with_include_filter():
    handler, manager = _handler()

    async with ProtocolSession(handler) as session:
        tools = await session.request(
            LangBotToRuntimeAction.LIST_TOOLS.value,
            {"include_plugins": ["tester/demo"]},
            seq_id=1,
        )
        commands = await session.request(
            LangBotToRuntimeAction.LIST_COMMANDS.value,
            {"include_plugins": ["tester/demo"]},
            seq_id=2,
        )

    assert tools["data"] == {"tools": [{"name": "weather"}]}
    assert commands["data"] == {"commands": [{"name": "start"}]}
    assert manager.calls == [
        ("list_tools", ["tester/demo"]),
        ("list_commands", ["tester/demo"]),
    ]


async def test_control_handler_call_tool_delegates_session_and_query_context():
    handler, manager = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(
            LangBotToRuntimeAction.CALL_TOOL.value,
            {
                "tool_name": "weather",
                "tool_parameters": {"city": "Shanghai"},
                "session": {"id": "s"},
                "query_id": 7,
                "include_plugins": ["tester/demo"],
            },
        )

    assert response["data"] == {"tool_response": {"text": "sunny"}}
    assert manager.calls == [
        (
            "call_tool",
            "weather",
            {"city": "Shanghai"},
            {"id": "s"},
            7,
            ["tester/demo"],
        )
    ]


async def test_control_handler_rag_and_parser_discovery_actions():
    handler, manager = _handler()

    async with ProtocolSession(handler) as session:
        engines = await session.request(
            LangBotToRuntimeAction.LIST_KNOWLEDGE_ENGINES.value,
            seq_id=1,
        )
        parsers = await session.request(
            LangBotToRuntimeAction.LIST_PARSERS.value,
            seq_id=2,
        )

    assert engines["data"] == {"engines": [{"name": "rag"}]}
    assert parsers["data"] == {"parsers": [{"name": "parser"}]}
    assert manager.calls == [("list_knowledge_engines",), ("list_parsers",)]


async def test_control_handler_rag_ingest_document_delegates_context():
    handler, manager = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(
            LangBotToRuntimeAction.RAG_INGEST_DOCUMENT.value,
            {
                "plugin_author": "tester",
                "plugin_name": "demo",
                "context": {"document_id": "doc"},
            },
        )

    assert response["data"] == {"document_id": "doc"}
    assert manager.calls == [
        (
            "rag_ingest_document",
            "tester",
            "demo",
            {"document_id": "doc"},
        )
    ]
