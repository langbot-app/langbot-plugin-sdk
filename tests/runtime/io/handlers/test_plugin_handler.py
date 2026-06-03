from __future__ import annotations

from types import SimpleNamespace

from langbot_plugin.entities.io.actions.enums import (
    PluginToRuntimeAction,
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
        return {"metadata": {"author": self.metadata.author, "name": self.metadata.name}}


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
        self.calls.append(
            ("call_tool", tool_name, tool_parameters, session, query_id)
        )
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
    monkeypatch.setattr(plugin_handler_module.runtime_settings, "plugin_debug_key", "key")

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.REGISTER_PLUGIN.value,
            {"plugin_container": {"id": "plugin"}, "plugin_debug_key": "key"},
        )

    assert response["code"] == 0
    assert manager.calls == [
        ("register_plugin", handler, {"id": "plugin"}, True)
    ]


async def test_plugin_handler_rejects_plugin_with_invalid_debug_key(monkeypatch):
    handler, manager, _control = _handler(debug_plugin=True)
    monkeypatch.setattr(plugin_handler_module.runtime_settings, "plugin_debug_key", "key")

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
    assert manager.calls == [
        ("register_plugin", handler, {"id": "plugin"}, False)
    ]


async def test_plugin_handler_forwards_invoke_llm_with_validated_timeout():
    handler, _manager, control = _handler()
    control.results[PluginToRuntimeAction.INVOKE_LLM] = {"message": "ok"}

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.INVOKE_LLM.value,
            {"messages": [], "timeout": -1},
        )

    assert response["data"] == {"message": "ok"}
    assert control.calls == [
        (PluginToRuntimeAction.INVOKE_LLM, {"messages": []}, 120.0)
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


async def test_plugin_handler_forwards_config_file_requests_to_langbot():
    handler, _manager, control = _handler()
    control.results[RuntimeToLangBotAction.GET_CONFIG_FILE] = {"file_base64": "Y29uZmln"}

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
    control.results[PluginToRuntimeAction.GET_KNOWLEDGE_FILE_STREAM] = {
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
                PluginToRuntimeAction.GET_KNOWLEDGE_FILE_STREAM.value,
                {"storage_path": "kb/doc"},
            )

    assert file_ops == [
        ("read", "host-file"),
        ("delete", "host-file"),
        ("send", b"file-bytes", ""),
    ]
    assert response["data"] == {"file_key": "plugin-file"}


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


async def test_plugin_handler_forwards_prompt_get():
    handler, _manager, control = _handler()
    control.results[PluginToRuntimeAction.PROMPT_GET] = {
        "prompt": [{"role": "system", "content": "Host prompt"}],
    }

    async with ProtocolSession(handler) as session:
        response = await session.request(
            PluginToRuntimeAction.PROMPT_GET.value,
            {"run_id": "run-1"},
        )

    assert response["data"] == {
        "prompt": [{"role": "system", "content": "Host prompt"}],
    }
    assert control.calls == [
        (
            PluginToRuntimeAction.PROMPT_GET,
            {"run_id": "run-1"},
            30,
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
