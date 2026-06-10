from __future__ import annotations

import base64

import pytest

from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain
from langbot_plugin.api.entities.builtin.provider.message import Message
from langbot_plugin.api.proxies.langbot_api import LangBotAPIProxy
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction


class FakeHandler:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls: list[tuple[PluginToRuntimeAction, dict, float | None]] = []
        self.local_files = {"file-key": b"file-bytes"}
        self.deleted_files: list[str] = []

    async def call_action(self, action, data, timeout=None):
        self.calls.append((action, data, timeout))
        response = self.responses.get(action)
        if callable(response):
            return response(data)
        if response is not None:
            return response
        return {}

    async def read_local_file(self, file_key: str) -> bytes:
        return self.local_files[file_key]

    async def delete_local_file(self, file_key: str) -> None:
        self.deleted_files.append(file_key)


@pytest.mark.asyncio
async def test_langbot_api_basic_read_methods_unwrap_response_fields():
    handler = FakeHandler(
        {
            PluginToRuntimeAction.GET_LANGBOT_VERSION: {"version": "1.2.3"},
            PluginToRuntimeAction.GET_BOTS: {"bots": ["bot"]},
            PluginToRuntimeAction.GET_BOT_INFO: {"bot": {"uuid": "bot"}},
            PluginToRuntimeAction.GET_LLM_MODELS: {"llm_models": ["model"]},
        }
    )
    proxy = LangBotAPIProxy(handler)

    assert await proxy.get_langbot_version() == "1.2.3"
    assert await proxy.get_bots() == ["bot"]
    assert await proxy.get_bot_info("bot") == {"uuid": "bot"}
    assert await proxy.get_llm_models() == ["model"]
    assert handler.calls[2] == (
        PluginToRuntimeAction.GET_BOT_INFO,
        {"bot_uuid": "bot"},
        None,
    )


@pytest.mark.asyncio
async def test_send_message_serializes_message_chain_payload():
    handler = FakeHandler()
    proxy = LangBotAPIProxy(handler)

    await proxy.send_message(
        "bot",
        "person",
        "target",
        MessageChain([Plain(text="hello")]),
    )

    action, data, timeout = handler.calls[0]
    assert action is PluginToRuntimeAction.SEND_MESSAGE
    assert data["message_chain"] == [{"type": "Plain", "text": "hello"}]
    assert timeout is None


@pytest.mark.asyncio
async def test_invoke_llm_serializes_messages_and_uses_effective_timeout():
    handler = FakeHandler(
        {
            PluginToRuntimeAction.INVOKE_LLM: {
                "message": {"role": "assistant", "content": "ok"}
            }
        }
    )
    proxy = LangBotAPIProxy(handler)

    result = await proxy.invoke_llm(
        "model",
        [Message(role="user", content="hello")],
        extra_args={"temperature": 0},
    )

    assert result == Message(role="assistant", content="ok")
    action, data, timeout = handler.calls[0]
    assert action is PluginToRuntimeAction.INVOKE_LLM
    assert data["timeout"] == 120.0
    assert timeout == 120.0


@pytest.mark.asyncio
async def test_storage_helpers_encode_and_decode_base64():
    handler = FakeHandler(
        {
            PluginToRuntimeAction.GET_PLUGIN_STORAGE: {
                "value_base64": base64.b64encode(b"value").decode()
            },
            PluginToRuntimeAction.GET_WORKSPACE_STORAGE: {
                "value_base64": base64.b64encode(b"workspace").decode()
            },
            PluginToRuntimeAction.GET_CONFIG_FILE: {
                "file_base64": base64.b64encode(b"config").decode()
            },
            PluginToRuntimeAction.GET_PLUGIN_STORAGE_KEYS: {"keys": ["a"]},
            PluginToRuntimeAction.GET_WORKSPACE_STORAGE_KEYS: {"keys": ["b"]},
        }
    )
    proxy = LangBotAPIProxy(handler)

    await proxy.set_plugin_storage("k", b"value")
    assert await proxy.get_plugin_storage("k") == b"value"
    assert await proxy.get_plugin_storage_keys() == ["a"]
    await proxy.delete_plugin_storage("k")
    await proxy.set_workspace_storage("w", b"workspace")
    assert await proxy.get_workspace_storage("w") == b"workspace"
    assert await proxy.get_workspace_storage_keys() == ["b"]
    await proxy.delete_workspace_storage("w")
    assert await proxy.get_config_file("cfg") == b"config"

    assert handler.calls[0][1] == {"key": "k", "value_base64": "dmFsdWU="}
    set_workspace_call = [
        call
        for call in handler.calls
        if call[0] is PluginToRuntimeAction.SET_WORKSPACE_STORAGE
    ][0]
    assert set_workspace_call[1] == {"key": "w", "value_base64": "d29ya3NwYWNl"}


@pytest.mark.asyncio
async def test_tool_and_rag_helpers_preserve_payload_contracts():
    handler = FakeHandler(
        {
            PluginToRuntimeAction.LIST_PLUGINS_MANIFEST: {"plugins": ["p"]},
            PluginToRuntimeAction.LIST_COMMANDS: {"commands": ["cmd"]},
            PluginToRuntimeAction.LIST_TOOLS: {"tools": [{"name": "tool"}]},
            PluginToRuntimeAction.GET_TOOL_DETAIL: {"tool": {"name": "tool"}},
            PluginToRuntimeAction.CALL_TOOL: {"tool_response": {"ok": True}},
            PluginToRuntimeAction.INVOKE_EMBEDDING: {"vectors": [[0.1]]},
            PluginToRuntimeAction.VECTOR_SEARCH: {"results": [{"id": "1"}]},
            PluginToRuntimeAction.VECTOR_DELETE: {"count": 2},
            PluginToRuntimeAction.VECTOR_LIST: {"items": [], "total": 0},
            PluginToRuntimeAction.LIST_KNOWLEDGE_BASES: {"knowledge_bases": []},
            PluginToRuntimeAction.RETRIEVE_KNOWLEDGE: {"results": []},
        }
    )
    proxy = LangBotAPIProxy(handler)

    assert await proxy.list_plugins_manifest() == ["p"]
    assert await proxy.list_commands() == ["cmd"]
    assert await proxy.list_tools() == [{"name": "tool"}]
    assert await proxy.get_tool_detail("tool") == {"name": "tool"}
    assert await proxy.call_tool("tool", {"q": 1}, {"s": 1}, 7) == {"ok": True}
    assert await proxy.invoke_embedding("embed", ["hi"]) == [[0.1]]
    await proxy.vector_upsert("c", [[0.1]], ["id"], documents=["doc"])
    assert await proxy.vector_search("c", [0.1], filters={"a": 1}) == [{"id": "1"}]
    assert await proxy.vector_delete("c", file_ids=["f"]) == 2
    assert await proxy.vector_list("c") == {"items": [], "total": 0}
    assert await proxy.list_knowledge_bases() == []
    assert await proxy.retrieve_knowledge("kb", "query") == []

    call_tool_call = [
        call for call in handler.calls if call[0] is PluginToRuntimeAction.CALL_TOOL
    ][0]
    assert call_tool_call[1]["tool_parameters"] == {"q": 1}
    assert call_tool_call[2] == 180


@pytest.mark.asyncio
async def test_get_knowledge_file_stream_reads_and_deletes_local_chunk_file():
    handler = FakeHandler(
        {PluginToRuntimeAction.GET_KNOWLEDEGE_FILE_STREAM: {"file_key": "file-key"}}
    )
    proxy = LangBotAPIProxy(handler)

    assert await proxy.get_knowledge_file_stream("storage/path") == b"file-bytes"
    assert handler.deleted_files == ["file-key"]


@pytest.mark.asyncio
async def test_parser_helpers_preserve_payload_contracts():
    handler = FakeHandler(
        {
            PluginToRuntimeAction.LIST_PARSERS: {"parsers": [{"name": "parser"}]},
            PluginToRuntimeAction.INVOKE_PARSER: {"text": "parsed"},
        }
    )
    proxy = LangBotAPIProxy(handler)

    assert await proxy.list_parsers("text/plain") == [{"name": "parser"}]
    assert await proxy.invoke_parser(
        "author",
        "parser",
        "files/a.txt",
        "text/plain",
        "a.txt",
    ) == {"text": "parsed"}
    assert handler.calls[-1] == (
        PluginToRuntimeAction.INVOKE_PARSER,
        {
            "plugin_author": "author",
            "plugin_name": "parser",
            "storage_path": "files/a.txt",
            "mime_type": "text/plain",
            "filename": "a.txt",
            "metadata": {},
        },
        300,
    )
