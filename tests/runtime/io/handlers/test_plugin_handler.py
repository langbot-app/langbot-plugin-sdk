from __future__ import annotations

import pytest
from types import SimpleNamespace

from langbot_plugin.entities.io.actions.enums import (
    PluginToRuntimeAction,
    RuntimeToPluginAction,
    RuntimeToLangBotAction,
)
import langbot_plugin.runtime.plugin.container  # noqa: F401
from langbot_plugin.runtime.io.handlers import plugin as plugin_handler_module
from langbot_plugin.runtime.io.handlers.plugin import PluginConnectionHandler

from tests.helpers.protocol import ProtocolConnection, ProtocolSession


class FakeManifest:
    def __init__(self, author="tester", name="demo"):
        self.metadata = SimpleNamespace(author=author, name=name)

    def model_dump(self, **kwargs):
        return {
            "metadata": {"author": self.metadata.author, "name": self.metadata.name}
        }


class FakePluginContainer:
    def __init__(self, runtime_handler=None):
        self._runtime_plugin_handler = runtime_handler
        self.manifest = FakeManifest()

    def model_dump(self, **kwargs):
        return {"manifest": self.manifest.model_dump()}


class FakeControlHandler:
    def __init__(self):
        self.calls = []
        self.results = {}

    async def call_action(self, action, data, timeout=15.0):
        self.calls.append((action, data, timeout))
        return self.results.get(action, {"ok": True})


class FakePluginManager:
    def __init__(self):
        self.plugins = []
        self.calls = []
        self.tools = []
        self.commands = []

    async def register_plugin(self, handler, plugin_container, debug_plugin):
        self.calls.append(("register_plugin", handler, plugin_container, debug_plugin))

    async def remove_plugin_container(self, plugin_container):
        self.calls.append(("remove_plugin_container", plugin_container))

    async def list_tools(self):
        self.calls.append(("list_tools",))
        return self.tools

    async def call_tool(self, tool_name, tool_parameters, session, query_id):
        self.calls.append(("call_tool", tool_name, tool_parameters, session, query_id))
        return {"text": "tool response"}

    async def list_commands(self):
        self.calls.append(("list_commands",))
        return self.commands


class FakeTool:
    def __init__(self, name):
        self.metadata = SimpleNamespace(name=name)

    def to_plain_dict(self):
        return {"name": self.metadata.name}


class Dumpable:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, **kwargs):
        return self.payload


def _handler(debug_plugin=False):
    control_handler = FakeControlHandler()
    manager = FakePluginManager()
    context = SimpleNamespace(control_handler=control_handler, plugin_mgr=manager)
    handler = PluginConnectionHandler(
        ProtocolConnection(),
        context,
        debug_plugin=debug_plugin,
    )
    return handler, manager, control_handler


async def test_plugin_handler_registers_plugin_when_debug_key_matches(monkeypatch):
    handler, manager, _control = _handler(debug_plugin=True)
    monkeypatch.setattr(
        plugin_handler_module.runtime_settings, "plugin_debug_key", "key"
    )

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.REGISTER_PLUGIN.value,
            {"plugin_container": {"id": "plugin"}, "plugin_debug_key": "key"},
        )

    assert response["code"] == 0
    assert manager.calls == [("register_plugin", handler, {"id": "plugin"}, True)]


async def test_plugin_handler_rejects_plugin_with_invalid_debug_key(monkeypatch):
    handler, manager, _control = _handler(debug_plugin=True)
    monkeypatch.setattr(
        plugin_handler_module.runtime_settings, "plugin_debug_key", "key"
    )

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.REGISTER_PLUGIN.value,
            {"plugin_container": {"id": "plugin"}, "plugin_debug_key": "wrong"},
        )

    assert response["code"] == 1
    assert response["message"] == "Plugin debug key verification failed"
    assert manager.calls == []


async def test_plugin_handler_prod_registration_disables_debug_mode(monkeypatch):
    handler, manager, _control = _handler(debug_plugin=True)
    monkeypatch.setattr(plugin_handler_module.runtime_settings, "plugin_debug_key", "")

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.REGISTER_PLUGIN.value,
            {"plugin_container": {"id": "plugin"}, "prod_mode": True},
        )

    assert response["code"] == 0
    assert handler.debug_plugin is False
    assert manager.calls == [("register_plugin", handler, {"id": "plugin"}, False)]


async def test_plugin_handler_forwards_invoke_llm_with_validated_timeout():
    handler, _manager, control = _handler()
    control.results[PluginToRuntimeAction.INVOKE_LLM] = {
        "message": "ok",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.INVOKE_LLM.value,
            {"messages": [], "timeout": -1},
        )

    assert response["data"] == {
        "message": "ok",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    assert control.calls == [
        (PluginToRuntimeAction.INVOKE_LLM, {"messages": []}, 120.0)
    ]


@pytest.mark.parametrize(
    ("action", "payload", "expected_action", "expected_payload", "expected_timeout"),
    [
        (
            PluginToRuntimeAction.REPLY_MESSAGE,
            {"query_id": 1, "message": "hi"},
            PluginToRuntimeAction.REPLY_MESSAGE,
            {"query_id": 1, "message": "hi"},
            180,
        ),
        (
            PluginToRuntimeAction.GET_BOT_UUID,
            {"query_id": 2},
            PluginToRuntimeAction.GET_BOT_UUID,
            {"query_id": 2},
            15.0,
        ),
        (
            PluginToRuntimeAction.SET_QUERY_VAR,
            {"query_id": 3, "key": "k", "value": "v"},
            PluginToRuntimeAction.SET_QUERY_VAR,
            {"query_id": 3, "key": "k", "value": "v"},
            15.0,
        ),
        (
            PluginToRuntimeAction.GET_QUERY_VAR,
            {"query_id": 3, "key": "k"},
            PluginToRuntimeAction.GET_QUERY_VAR,
            {"query_id": 3, "key": "k"},
            15.0,
        ),
        (
            PluginToRuntimeAction.GET_QUERY_VARS,
            {"query_id": 3},
            PluginToRuntimeAction.GET_QUERY_VARS,
            {"query_id": 3},
            15.0,
        ),
        (
            PluginToRuntimeAction.CREATE_NEW_CONVERSATION,
            {"query_id": 4, "ignored": "value"},
            PluginToRuntimeAction.CREATE_NEW_CONVERSATION,
            {"query_id": 4},
            15.0,
        ),
        (
            PluginToRuntimeAction.GET_LANGBOT_VERSION,
            {},
            PluginToRuntimeAction.GET_LANGBOT_VERSION,
            {},
            15.0,
        ),
        (
            PluginToRuntimeAction.GET_BOTS,
            {},
            PluginToRuntimeAction.GET_BOTS,
            {},
            15.0,
        ),
        (
            PluginToRuntimeAction.GET_BOT_INFO,
            {"bot_uuid": "bot-1"},
            PluginToRuntimeAction.GET_BOT_INFO,
            {"bot_uuid": "bot-1"},
            15.0,
        ),
        (
            PluginToRuntimeAction.SEND_MESSAGE,
            {"bot_uuid": "bot-1", "message": "hi"},
            PluginToRuntimeAction.SEND_MESSAGE,
            {"bot_uuid": "bot-1", "message": "hi"},
            15.0,
        ),
        (
            PluginToRuntimeAction.GET_LLM_MODELS,
            {},
            PluginToRuntimeAction.GET_LLM_MODELS,
            {},
            15.0,
        ),
        (
            PluginToRuntimeAction.INVOKE_EMBEDDING,
            {"model": "embed", "texts": ["hello"]},
            PluginToRuntimeAction.INVOKE_EMBEDDING,
            {"model": "embed", "texts": ["hello"]},
            60,
        ),
        (
            PluginToRuntimeAction.INVOKE_RERANK,
            {"model": "rerank", "query": "q", "docs": ["d"]},
            PluginToRuntimeAction.INVOKE_RERANK,
            {"model": "rerank", "query": "q", "docs": ["d"]},
            60,
        ),
        (
            PluginToRuntimeAction.VECTOR_UPSERT,
            {"collection_id": "kb", "points": []},
            PluginToRuntimeAction.VECTOR_UPSERT,
            {"collection_id": "kb", "points": []},
            60,
        ),
        (
            PluginToRuntimeAction.VECTOR_SEARCH,
            {"collection_id": "kb", "vector": [0.1]},
            PluginToRuntimeAction.VECTOR_SEARCH,
            {"collection_id": "kb", "vector": [0.1]},
            30,
        ),
        (
            PluginToRuntimeAction.VECTOR_DELETE,
            {"collection_id": "kb", "ids": ["p1"]},
            PluginToRuntimeAction.VECTOR_DELETE,
            {"collection_id": "kb", "ids": ["p1"]},
            30,
        ),
        (
            PluginToRuntimeAction.LIST_KNOWLEDGE_BASES,
            {},
            PluginToRuntimeAction.LIST_KNOWLEDGE_BASES,
            {},
            15.0,
        ),
        (
            PluginToRuntimeAction.RETRIEVE_KNOWLEDGE,
            {"query": "hello"},
            PluginToRuntimeAction.RETRIEVE_KNOWLEDGE,
            {"query": "hello"},
            30,
        ),
        (
            PluginToRuntimeAction.LIST_PIPELINE_KNOWLEDGE_BASES,
            {"query_id": 5},
            PluginToRuntimeAction.LIST_PIPELINE_KNOWLEDGE_BASES,
            {"query_id": 5},
            15.0,
        ),
        (
            PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE,
            {"query_id": 5, "query": "hello"},
            PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE,
            {"query_id": 5, "query": "hello"},
            30,
        ),
        (
            PluginToRuntimeAction.LIST_PARSERS,
            {},
            PluginToRuntimeAction.LIST_PARSERS,
            {},
            30,
        ),
        (
            PluginToRuntimeAction.INVOKE_PARSER,
            {"parser": "pdf", "file_key": "file"},
            PluginToRuntimeAction.INVOKE_PARSER,
            {"parser": "pdf", "file_key": "file"},
            300,
        ),
    ],
)
async def test_plugin_handler_proxies_control_actions(
    action,
    payload,
    expected_action,
    expected_payload,
    expected_timeout,
):
    handler, _manager, control = _handler()
    control.results[expected_action] = {"proxied": expected_action.value}

    async with ProtocolSession(handler) as session:
        response = await session.request(action.value, dict(payload))

    assert response["data"] == {"proxied": expected_action.value}
    assert control.calls == [(expected_action, expected_payload, expected_timeout)]


async def test_plugin_handler_forwards_invoke_llm_with_custom_timeout():
    handler, _manager, control = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.INVOKE_LLM.value,
            {"messages": [], "timeout": 30},
        )

    assert response["code"] == 0
    assert control.calls == [(PluginToRuntimeAction.INVOKE_LLM, {"messages": []}, 30.0)]


async def test_plugin_handler_forwards_invoke_rerank_with_caller_identity():
    handler, manager, control = _handler()
    manager.plugins = [FakePluginContainer(runtime_handler=handler)]
    control.results[PluginToRuntimeAction.INVOKE_RERANK] = {
        "results": [{"index": 0, "relevance_score": 0.95}]
    }

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.INVOKE_RERANK.value,
            {
                "run_id": "run-1",
                "rerank_model_uuid": "rerank-model",
                "query": "query",
                "documents": ["doc"],
                "top_k": 1,
                "extra_args": {},
                "caller_plugin_identity": "spoofed/plugin",
            },
        )

    assert response["data"] == {"results": [{"index": 0, "relevance_score": 0.95}]}
    assert control.calls == [
        (
            PluginToRuntimeAction.INVOKE_RERANK,
            {
                "run_id": "run-1",
                "rerank_model_uuid": "rerank-model",
                "query": "query",
                "documents": ["doc"],
                "top_k": 1,
                "extra_args": {},
                "caller_plugin_identity": "tester/demo",
            },
            60,
        )
    ]


async def test_plugin_handler_adds_plugin_owner_for_binary_storage():
    handler, manager, control = _handler()
    manager.plugins = [FakePluginContainer(runtime_handler=handler)]

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.SET_PLUGIN_STORAGE.value,
            {"key": "cache", "value_base64": "dmFsdWU="},
        )

    assert response["code"] == 0
    assert control.calls == [
        (
            RuntimeToLangBotAction.SET_BINARY_STORAGE,
            {
                "key": "cache",
                "value_base64": "dmFsdWU=",
                "owner_type": "plugin",
                "owner": "tester/demo",
                "caller_plugin_identity": "tester/demo",
            },
            15.0,
        )
    ]


@pytest.mark.parametrize(
    ("action", "expected_action"),
    [
        (
            PluginToRuntimeAction.GET_PLUGIN_STORAGE,
            RuntimeToLangBotAction.GET_BINARY_STORAGE,
        ),
        (
            PluginToRuntimeAction.GET_PLUGIN_STORAGE_KEYS,
            RuntimeToLangBotAction.GET_BINARY_STORAGE_KEYS,
        ),
        (
            PluginToRuntimeAction.DELETE_PLUGIN_STORAGE,
            RuntimeToLangBotAction.DELETE_BINARY_STORAGE,
        ),
    ],
)
async def test_plugin_handler_plugin_storage_actions_add_owner(action, expected_action):
    handler, manager, control = _handler()
    manager.plugins = [FakePluginContainer(runtime_handler=handler)]

    async with ProtocolSession(handler) as session:
        response = await session.request(action.value, {"key": "cache"})

    assert response["code"] == 0
    assert control.calls == [
        (
            expected_action,
            {
                "key": "cache",
                "owner_type": "plugin",
                "owner": "tester/demo",
                "caller_plugin_identity": "tester/demo",
            },
            15.0,
        )
    ]


async def test_plugin_handler_workspace_storage_uses_default_workspace_owner():
    handler, _manager, control = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.GET_WORKSPACE_STORAGE.value,
            {"key": "shared"},
        )

    assert response["code"] == 0
    assert control.calls == [
        (
            RuntimeToLangBotAction.GET_BINARY_STORAGE,
            {"key": "shared", "owner_type": "workspace", "owner": "default"},
            15.0,
        )
    ]


@pytest.mark.parametrize(
    ("action", "expected_action"),
    [
        (
            PluginToRuntimeAction.SET_WORKSPACE_STORAGE,
            RuntimeToLangBotAction.SET_BINARY_STORAGE,
        ),
        (
            PluginToRuntimeAction.GET_WORKSPACE_STORAGE_KEYS,
            RuntimeToLangBotAction.GET_BINARY_STORAGE_KEYS,
        ),
        (
            PluginToRuntimeAction.DELETE_WORKSPACE_STORAGE,
            RuntimeToLangBotAction.DELETE_BINARY_STORAGE,
        ),
    ],
)
async def test_plugin_handler_workspace_storage_actions_use_default_owner(
    action,
    expected_action,
):
    handler, _manager, control = _handler()

    async with ProtocolSession(handler) as session:
        response = await session.request(action.value, {"key": "shared"})

    assert response["code"] == 0
    assert control.calls == [
        (
            expected_action,
            {"key": "shared", "owner_type": "workspace", "owner": "default"},
            15.0,
        )
    ]


async def test_plugin_handler_forwards_config_file_requests_to_langbot():
    handler, _manager, control = _handler()
    control.results[RuntimeToLangBotAction.GET_CONFIG_FILE] = {
        "file_base64": "Y29uZmln"
    }

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.GET_CONFIG_FILE.value,
            {"file_key": "settings.yaml"},
        )

    assert response["data"] == {"file_base64": "Y29uZmln"}
    assert control.calls == [
        (
            RuntimeToLangBotAction.GET_CONFIG_FILE,
            {
                "file_key": "settings.yaml",
                "run_id": None,
                "caller_plugin_identity": None,
            },
            15.0,
        )
    ]


async def test_plugin_handler_get_knowledge_file_stream_repackages_file(monkeypatch):
    handler, _manager, control = _handler()
    file_ops = []
    control.results[PluginToRuntimeAction.GET_KNOWLEDEGE_FILE_STREAM] = {
        "file_key": "host-file"
    }

    async def fake_read_local_file(file_key):
        file_ops.append(("read", file_key))
        return b"file-bytes"

    async def fake_delete_local_file(file_key):
        file_ops.append(("delete", file_key))

    async def fake_send_file(file_bytes, extension):
        file_ops.append(("send", file_bytes, extension))
        return "plugin-file"

    monkeypatch.setattr(handler, "read_local_file", fake_read_local_file)
    monkeypatch.setattr(handler, "delete_local_file", fake_delete_local_file)
    monkeypatch.setattr(handler, "send_file", fake_send_file)

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.GET_KNOWLEDEGE_FILE_STREAM.value,
            {"storage_path": "kb/doc"},
        )

    assert file_ops == [
        ("read", "host-file"),
        ("delete", "host-file"),
        ("send", b"file-bytes", ""),
    ]
    assert response["data"] == {"file_key": "plugin-file"}


async def test_plugin_handler_get_knowledge_file_stream_returns_empty_result():
    handler, _manager, control = _handler()
    control.results[PluginToRuntimeAction.GET_KNOWLEDEGE_FILE_STREAM] = {"file_key": ""}

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.GET_KNOWLEDEGE_FILE_STREAM.value,
            {"storage_path": "kb/doc"},
        )

    assert response["data"] == {"file_key": ""}


async def test_plugin_handler_lists_tools_and_reports_missing_tool_detail():
    handler, manager, control = _handler()
    manager.tools = [FakeTool("weather")]
    control.results[PluginToRuntimeAction.GET_TOOL_DETAIL] = {
        "tool": {"name": "missing"},
    }

    async with ProtocolSession(handler) as session:
        listed = await session.request(PluginToRuntimeAction.LIST_TOOLS.value, seq_id=1)
        missing = await session.request(
            PluginToRuntimeAction.GET_TOOL_DETAIL.value,
            {"tool_name": "missing"},
            seq_id=2,
        )

    assert listed["data"] == {"tools": [{"name": "weather"}]}
    assert missing["data"] == {"tool": {"name": "missing"}}
    assert control.calls == [
        (
            PluginToRuntimeAction.GET_TOOL_DETAIL,
            {"tool_name": "missing"},
            30,
        )
    ]


async def test_plugin_handler_get_tool_detail_returns_matching_tool():
    handler, manager, control = _handler()
    manager.tools = [FakeTool("weather")]
    control.results[PluginToRuntimeAction.GET_TOOL_DETAIL] = {
        "tool": {"name": "weather"}
    }

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.GET_TOOL_DETAIL.value,
            {"tool_name": "weather"},
        )

    assert response["data"] == {"tool": {"name": "weather"}}
    assert control.calls == [
        (
            PluginToRuntimeAction.GET_TOOL_DETAIL,
            {"tool_name": "weather"},
            30,
        )
    ]


async def test_plugin_handler_calls_registered_runtime_tool():
    handler, _manager, control = _handler()
    control.results[PluginToRuntimeAction.CALL_TOOL] = {
        "tool_response": {"text": "tool response"}
    }

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.CALL_TOOL.value,
            {
                "tool_name": "weather",
                "tool_parameters": {"city": "Shanghai"},
                "session": {"id": "s"},
                "query_id": 7,
            },
        )

    assert response["data"] == {"tool_response": {"text": "tool response"}}
    assert control.calls == [
        (
            PluginToRuntimeAction.CALL_TOOL,
            {
                "tool_name": "weather",
                "tool_parameters": {"city": "Shanghai"},
                "session": {"id": "s"},
                "query_id": 7,
            },
            180.0,
        )
    ]


async def test_plugin_handler_forwards_agent_runner_tool_envelope():
    handler, _manager, control = _handler()
    control.results[PluginToRuntimeAction.CALL_TOOL] = {
        "result": {"text": "tool response"}
    }

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.CALL_TOOL.value,
            {
                "run_id": "run-1",
                "tool_name": "weather",
                "parameters": {"city": "Shanghai"},
            },
        )

    assert response["data"] == {"result": {"text": "tool response"}}
    assert control.calls == [
        (
            PluginToRuntimeAction.CALL_TOOL,
            {
                "run_id": "run-1",
                "tool_name": "weather",
                "parameters": {"city": "Shanghai"},
            },
            180.0,
        )
    ]


async def test_plugin_handler_lists_plugin_manifests():
    handler, manager, _control = _handler()
    manager.plugins = [FakePluginContainer()]

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.LIST_PLUGINS_MANIFEST.value
        )

    assert response["data"] == {
        "plugins": [{"metadata": {"author": "tester", "name": "demo"}}]
    }


async def test_plugin_handler_lists_commands():
    handler, manager, _control = _handler()
    manager.commands = [Dumpable({"name": "admin"})]

    async with ProtocolSession(handler) as session:
        response = await session.request(PluginToRuntimeAction.LIST_COMMANDS.value)

    assert response["data"] == {"commands": [{"name": "admin"}]}


async def test_plugin_connection_handler_peer_call_helpers(monkeypatch):
    handler, _manager, _control = _handler()
    calls = []

    async def fake_call_action(action, data, timeout=15.0):
        calls.append((action, data, timeout))
        return {"action": action.value, "data": data}

    monkeypatch.setattr(handler, "call_action", fake_call_action)

    assert await handler.initialize_plugin({"enabled": True}) == {
        "action": RuntimeToPluginAction.INITIALIZE_PLUGIN.value,
        "data": {"plugin_settings": {"enabled": True}},
    }
    assert await handler.get_plugin_container() == {
        "action": RuntimeToPluginAction.GET_PLUGIN_CONTAINER.value,
        "data": {},
    }
    assert await handler.get_plugin_icon() == {
        "action": RuntimeToPluginAction.GET_PLUGIN_ICON.value,
        "data": {},
    }
    assert await handler.get_plugin_readme("zh") == {
        "action": RuntimeToPluginAction.GET_PLUGIN_README.value,
        "data": {"language": "zh"},
    }
    assert await handler.get_plugin_assets_file("asset.txt") == {
        "action": RuntimeToPluginAction.GET_PLUGIN_ASSETS_FILE.value,
        "data": {"file_key": "asset.txt"},
    }
    assert await handler.call_page_api(
        page_id="settings",
        endpoint="/save",
        method="POST",
        body={"enabled": True},
    ) == {
        "action": RuntimeToPluginAction.PAGE_API.value,
        "data": {
            "page_id": "settings",
            "endpoint": "/save",
            "method": "POST",
            "body": {"enabled": True},
        },
    }
    assert await handler.emit_event({"event_name": "PersonMessageReceived"}) == {
        "action": RuntimeToPluginAction.EMIT_EVENT.value,
        "data": {"event_context": {"event_name": "PersonMessageReceived"}},
    }
    assert await handler.call_tool("weather", {"city": "Paris"}, {"id": "s"}, 9) == {
        "action": RuntimeToPluginAction.CALL_TOOL.value,
        "data": {
            "tool_name": "weather",
            "tool_parameters": {"city": "Paris"},
            "session": {"id": "s"},
            "query_id": 9,
        },
    }
    assert await handler.retrieve_knowledge("kb", {"query": "hi"}) == {
        "action": RuntimeToPluginAction.RETRIEVE_KNOWLEDGE.value,
        "data": {"retriever_name": "kb", "retrieval_context": {"query": "hi"}},
    }
    assert await handler.shutdown_plugin() == {
        "action": RuntimeToPluginAction.SHUTDOWN.value,
        "data": {},
    }
    assert await handler.rag_ingest_document({"document_id": "doc-1"}) == {
        "action": RuntimeToPluginAction.INGEST_DOCUMENT.value,
        "data": {"context": {"document_id": "doc-1"}},
    }
    assert await handler.rag_delete_document("kb-1", "doc-1") == {
        "action": RuntimeToPluginAction.DELETE_DOCUMENT.value,
        "data": {"kb_id": "kb-1", "document_id": "doc-1"},
    }
    assert await handler.rag_on_kb_create("kb-1", {"top_k": 3}) == {
        "action": RuntimeToPluginAction.ON_KB_CREATE.value,
        "data": {"kb_id": "kb-1", "config": {"top_k": 3}},
    }
    assert await handler.rag_on_kb_delete("kb-1") == {
        "action": RuntimeToPluginAction.ON_KB_DELETE.value,
        "data": {"kb_id": "kb-1"},
    }
    assert await handler.get_rag_capabilities() == {
        "action": RuntimeToPluginAction.GET_RAG_CAPABILITIES.value,
        "data": {},
    }
    assert calls[-1] == (RuntimeToPluginAction.GET_RAG_CAPABILITIES, {}, 10)


async def test_plugin_connection_handler_notify_plugin_diagnostic_helper(monkeypatch):
    handler, _manager, _control = _handler()
    calls = []

    async def fake_call_action(action, data, timeout=15.0):
        calls.append((action, data, timeout))
        return {"ok": True}

    monkeypatch.setattr(handler, "call_action", fake_call_action)

    result = await handler.notify_plugin_diagnostic({"level": "ERROR"})

    assert result == {"ok": True}
    assert calls == [(RuntimeToPluginAction.PLUGIN_DIAGNOSTIC, {"level": "ERROR"}, 5)]


async def test_plugin_connection_handler_execute_command_and_parse_document_helpers(
    monkeypatch,
):
    handler, _manager, _control = _handler()
    calls = []

    async def fake_generator(action, data, timeout=15.0):
        calls.append(("generator", action, data, timeout))
        yield {"command_response": {"text": "one"}}
        yield {"command_response": {"text": "two"}}

    async def fake_send_file(file_bytes, extension):
        calls.append(("send_file", file_bytes, extension))
        return "file-key"

    async def fake_call_action(action, data, timeout=15.0):
        calls.append(("call_action", action, data, timeout))
        return {"parsed": data}

    monkeypatch.setattr(handler, "call_action_generator", fake_generator)
    monkeypatch.setattr(handler, "send_file", fake_send_file)
    monkeypatch.setattr(handler, "call_action", fake_call_action)

    command_chunks = [
        chunk async for chunk in handler.execute_command({"command": "admin"})
    ]
    parse_result = await handler.parse_document({"filename": "a.pdf"}, b"pdf")

    assert command_chunks == [
        {"command_response": {"text": "one"}},
        {"command_response": {"text": "two"}},
    ]
    assert calls[0] == (
        "generator",
        RuntimeToPluginAction.EXECUTE_COMMAND,
        {"command_context": {"command": "admin"}},
        plugin_handler_module.LONG_RUNNING_OPERATION_TIMEOUT,
    )
    assert parse_result == {
        "parsed": {"context": {"filename": "a.pdf", "file_key": "file-key"}}
    }
    assert calls[-2:] == [
        ("send_file", b"pdf", ""),
        (
            "call_action",
            RuntimeToPluginAction.PARSE_DOCUMENT,
            {"context": {"filename": "a.pdf", "file_key": "file-key"}},
            300,
        ),
    ]
