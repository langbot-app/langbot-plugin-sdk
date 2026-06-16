from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.knowledge_engine.engine import (
    KnowledgeEngine,
)
from langbot_plugin.api.definition.components.page import Page, PageRequest
from langbot_plugin.api.definition.components.parser.parser import Parser
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.rag.context import (
    RetrievalResponse,
    RetrievalResultEntry,
)
from langbot_plugin.api.entities.builtin.rag.enums import DocumentStatus
from langbot_plugin.api.entities.builtin.rag.models import (
    IngestionResult,
    ParseResult,
)
from langbot_plugin.api.entities.builtin.provider.message import ContentElement
from langbot_plugin.cli.run.handler import PluginRuntimeHandler, _resolve_asset_path
from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction

from tests.helpers.protocol import ProtocolConnection, ProtocolSession


class FakeManifest:
    def __init__(
        self,
        kind: str = "Plugin",
        name: str = "demo",
        component_class=None,
    ):
        self.kind = kind
        self.metadata = SimpleNamespace(name=name)
        self.icon_rel_path = None
        self._component_class = component_class

    def model_dump(self, **kwargs):
        return {
            "kind": self.kind,
            "metadata": {"name": self.metadata.name},
        }

    def get_python_component_class(self):
        if self._component_class is None:
            raise AssertionError("component class not configured")
        return self._component_class


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
    def __init__(
        self,
        kind: str,
        name: str,
        component_instance,
        component_class=None,
    ):
        self.manifest = FakeManifest(
            kind=kind,
            name=name,
            component_class=component_class,
        )
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


class SimpleTool(Tool):
    async def call(self, params):
        return {"ok": True, "params": params}


class FakeKnowledgeEngine(KnowledgeEngine):
    def __init__(self):
        self.created = []
        self.deleted = []

    @classmethod
    def get_capabilities(cls):
        return ["doc_ingestion", "doc_parsing"]

    async def ingest(self, context):
        return IngestionResult(
            document_id=context.file_object.metadata.document_id,
            status=DocumentStatus.COMPLETED,
            chunks_created=2,
            metadata={"collection_id": context.get_collection_id()},
        )

    async def delete_document(self, kb_id: str, document_id: str) -> bool:
        self.deleted.append((kb_id, document_id))
        return True

    async def retrieve(self, context):
        return RetrievalResponse(
            results=[
                RetrievalResultEntry(
                    id="chunk-1",
                    content=[ContentElement.from_text(f"answer:{context.query}")],
                    metadata={"kb": context.get_collection_id()},
                    distance=0.1,
                    score=0.9,
                )
            ],
            total_found=1,
        )

    async def on_knowledge_base_create(self, kb_id: str, config: dict) -> None:
        self.created.append((kb_id, config))

    async def on_knowledge_base_delete(self, kb_id: str) -> None:
        self.deleted.append((kb_id, None))


class FakeParser(Parser):
    async def parse(self, context):
        return ParseResult(
            text=context.file_content.decode() or context.filename,
            metadata={"mime_type": context.mime_type},
        )


def _handler():
    initialized = []

    async def initialize(plugin_settings):
        initialized.append(plugin_settings)

    handler = PluginRuntimeHandler(ProtocolConnection(), initialize)
    handler.plugin_container = FakePluginContainer()
    return handler, initialized


def test_resolve_asset_path_accepts_assets_and_component_page_files(
    tmp_path, monkeypatch
):
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


async def test_plugin_runtime_handler_call_tool_supports_simple_call_signature():
    handler, _initialized = _handler()
    handler.plugin_container.components = [
        FakeComponentContainer(Tool.__kind__, "simple", SimpleTool())
    ]

    async with ProtocolSession(handler) as session:
        response = await session.request(
            RuntimeToPluginAction.CALL_TOOL.value,
            {
                "tool_name": "simple",
                "tool_parameters": {"x": 1},
                "session": {},
                "query_id": 1,
            },
        )

    assert response["data"] == {"tool_response": {"ok": True, "params": {"x": 1}}}


async def test_plugin_runtime_handler_knowledge_engine_actions_succeed():
    handler, _initialized = _handler()
    engine = FakeKnowledgeEngine()
    handler.plugin_container.components = [
        FakeComponentContainer(
            KnowledgeEngine.__kind__,
            "kb",
            engine,
            component_class=FakeKnowledgeEngine,
        )
    ]

    async with ProtocolSession(handler) as session:
        retrieve = await session.request(
            RuntimeToPluginAction.RETRIEVE_KNOWLEDGE.value,
            {
                "retriever_name": "kb",
                "retrieval_context": {
                    "query": "hello",
                    "knowledge_base_id": "kb-1",
                },
            },
            seq_id=1,
        )
        ingest = await session.request(
            RuntimeToPluginAction.INGEST_DOCUMENT.value,
            {
                "context": {
                    "knowledge_base_id": "kb-1",
                    "file_object": {
                        "metadata": {
                            "filename": "a.md",
                            "file_size": 4,
                            "mime_type": "text/markdown",
                            "document_id": "doc-1",
                            "knowledge_base_id": "kb-1",
                        },
                        "storage_path": "files/doc-1",
                    },
                }
            },
            seq_id=2,
        )
        delete_doc = await session.request(
            RuntimeToPluginAction.DELETE_DOCUMENT.value,
            {"kb_id": "kb-1", "document_id": "doc-1"},
            seq_id=3,
        )
        create_kb = await session.request(
            RuntimeToPluginAction.ON_KB_CREATE.value,
            {"kb_id": "kb-2", "config": {"top_k": 3}},
            seq_id=4,
        )
        delete_kb = await session.request(
            RuntimeToPluginAction.ON_KB_DELETE.value,
            {"kb_id": "kb-2"},
            seq_id=5,
        )
        capabilities = await session.request(
            RuntimeToPluginAction.GET_RAG_CAPABILITIES.value,
            seq_id=6,
        )

    assert retrieve["data"]["total_found"] == 1
    assert retrieve["data"]["results"][0]["content"][0]["text"] == "answer:hello"
    assert ingest["data"]["document_id"] == "doc-1"
    assert ingest["data"]["chunks_created"] == 2
    assert delete_doc["data"] == {"success": True}
    assert create_kb["data"] == {"success": True}
    assert delete_kb["data"] == {"success": True}
    assert capabilities["data"] == {"capabilities": ["doc_ingestion", "doc_parsing"]}
    assert engine.created == [("kb-2", {"top_k": 3})]
    assert engine.deleted == [("kb-1", "doc-1"), ("kb-2", None)]


async def test_plugin_runtime_handler_knowledge_engine_reports_missing_states():
    handler, _initialized = _handler()

    async with ProtocolSession(handler) as session:
        missing = await session.request(
            RuntimeToPluginAction.RETRIEVE_KNOWLEDGE.value,
            {"retriever_name": "kb", "retrieval_context": {"query": "hello"}},
            seq_id=1,
        )
        missing_capabilities = await session.request(
            RuntimeToPluginAction.GET_RAG_CAPABILITIES.value,
            seq_id=2,
        )

    assert missing["code"] == 1
    assert missing["message"] == "KnowledgeEngine kb not found"
    assert missing_capabilities["code"] == 1
    assert (
        missing_capabilities["message"]
        == "KnowledgeEngine component not found in this plugin"
    )

    handler, _initialized = _handler()
    handler.plugin_container.components = [
        FakeComponentContainer(KnowledgeEngine.__kind__, "kb", NoneComponent())
    ]
    async with ProtocolSession(handler) as session:
        uninitialized = await session.request(
            RuntimeToPluginAction.INGEST_DOCUMENT.value,
            {
                "context": {
                    "knowledge_base_id": "kb-1",
                    "file_object": {
                        "metadata": {
                            "filename": "a.md",
                            "file_size": 4,
                            "mime_type": "text/markdown",
                            "document_id": "doc-1",
                            "knowledge_base_id": "kb-1",
                        },
                        "storage_path": "files/doc-1",
                    },
                }
            },
        )

    assert uninitialized["code"] == 1
    assert uninitialized["message"] == "KnowledgeEngine component is not initialized"


async def test_plugin_runtime_handler_parser_actions_succeed(tmp_path, monkeypatch):
    handler, _initialized = _handler()
    handler.plugin_container.components = [
        FakeComponentContainer(Parser.__kind__, "pdf", FakeParser())
    ]
    read_keys = []
    deleted_keys = []

    async def fake_read_local_file(file_key):
        read_keys.append(file_key)
        return b"parsed bytes"

    async def fake_delete_local_file(file_key):
        deleted_keys.append(file_key)

    monkeypatch.setattr(handler, "read_local_file", fake_read_local_file)
    monkeypatch.setattr(handler, "delete_local_file", fake_delete_local_file)

    async with ProtocolSession(handler) as session:
        response = await session.request(
            RuntimeToPluginAction.PARSE_DOCUMENT.value,
            {
                "context": {
                    "file_key": "file-key",
                    "mime_type": "application/pdf",
                    "filename": "a.pdf",
                    "metadata": {"page": 1},
                }
            },
        )

    assert response["data"] == {
        "text": "parsed bytes",
        "sections": [],
        "metadata": {"mime_type": "application/pdf"},
    }
    assert read_keys == ["file-key"]
    assert deleted_keys == ["file-key"]


async def test_plugin_runtime_handler_parser_reports_missing_states():
    handler, _initialized = _handler()

    async with ProtocolSession(handler) as session:
        missing = await session.request(
            RuntimeToPluginAction.PARSE_DOCUMENT.value,
            {"context": {"filename": "a.pdf"}},
            seq_id=1,
        )

    assert missing["code"] == 1
    assert missing["message"] == "Parser component not found in this plugin"

    handler, _initialized = _handler()
    handler.plugin_container.components = [
        FakeComponentContainer(Parser.__kind__, "pdf", NoneComponent())
    ]
    async with ProtocolSession(handler) as session:
        uninitialized = await session.request(
            RuntimeToPluginAction.PARSE_DOCUMENT.value,
            {"context": {"filename": "a.pdf"}},
            seq_id=2,
        )

    assert uninitialized["code"] == 1
    assert uninitialized["message"] == "Parser component is not initialized"


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
