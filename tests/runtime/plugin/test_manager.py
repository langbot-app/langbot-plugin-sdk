from __future__ import annotations

import asyncio
import io
import zipfile
from types import SimpleNamespace
from typing import Any

import pytest

from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.api.definition.plugin import NonePlugin
from langbot_plugin.api.entities.builtin.command.context import CommandReturn
from langbot_plugin.api.entities.context import EventContext
from langbot_plugin.api.entities.events import PersonCommandSent
from langbot_plugin.runtime.plugin.container import (
    ComponentContainer,
    PluginContainer,
    RuntimeContainerStatus,
)
from langbot_plugin.runtime.plugin.mgr import PluginInstallSource, PluginManager


def _manifest(
    kind: str = "Plugin",
    name: str = "demo",
    author: str = "tester",
    spec: dict[str, Any] | None = None,
) -> ComponentManifest:
    return ComponentManifest(
        owner=author,
        rel_path=f"{name}.yaml",
        manifest={
            "apiVersion": "v1",
            "kind": kind,
            "metadata": {
                "name": name,
                "label": {"en_US": name.title()},
                "author": author,
                "version": "1.0.0",
            },
            "spec": spec or {},
        },
    )


def _component(kind: str, name: str, spec: dict[str, Any] | None = None):
    return ComponentContainer(
        manifest=_manifest(kind=kind, name=name, spec=spec),
        component_instance=NoneComponent(),
        component_config={},
    )


def _plugin(
    name: str = "demo",
    author: str = "tester",
    *,
    components: list[ComponentContainer] | None = None,
    status: RuntimeContainerStatus = RuntimeContainerStatus.INITIALIZED,
    enabled: bool = True,
    debug: bool = False,
) -> PluginContainer:
    return PluginContainer(
        debug=debug,
        install_source="local",
        install_info={},
        manifest=_manifest(name=name, author=author),
        plugin_instance=NonePlugin(),
        enabled=enabled,
        priority=0,
        plugin_config={},
        status=status,
        components=components or [],
    )


def _manager() -> PluginManager:
    manager = PluginManager(SimpleNamespace(ws_debug_port=18080))
    manager.plugins = []
    manager.plugin_handlers = []
    manager.plugin_run_tasks = []
    return manager


def _plugin_zip(author: str = "tester", name: str = "demo", version: str = "1.0.0"):
    manifest = f"""
apiVersion: v1
kind: Plugin
metadata:
  name: {name}
  label:
    en_US: Demo
  author: {author}
  version: {version}
spec: {{}}
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.yaml", manifest)
        archive.writestr("main.py", "")
    return buffer.getvalue()


class FakeControlHandler:
    def __init__(self):
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def call_action(self, action, payload):
        self.calls.append((action, payload))
        return {
            "enabled": True,
            "priority": 7,
            "plugin_config": {"api_key": "secret"},
            "install_source": PluginInstallSource.MARKETPLACE.value,
            "install_info": {"plugin_version": "1.0.0"},
        }


class FakeConnection:
    closed = False

    async def close(self):
        self.closed = True


class FakeHandler:
    def __init__(self, plugin: PluginContainer):
        self.plugin = plugin
        self.debug_plugin = False
        self.conn = FakeConnection()
        self.stdio_process = None
        self.initialized_with = None
        self.shutdown_calls = 0
        self.files = {
            "icon-key": b"<svg/>",
            "readme-key": b"# Demo",
            "asset-key": b"asset-bytes",
        }

    async def initialize_plugin(self, plugin_settings):
        self.initialized_with = plugin_settings

    async def get_plugin_container(self):
        refreshed = self.plugin.model_dump()
        refreshed["status"] = RuntimeContainerStatus.INITIALIZED.value
        return refreshed

    async def shutdown_plugin(self):
        self.shutdown_calls += 1

    async def emit_event(self, event_context):
        return {"emitted": True, "event_context": event_context}

    async def call_tool(self, tool_name, tool_parameters, session, query_id):
        return {
            "tool_response": {
                "tool_name": tool_name,
                "params": tool_parameters,
                "query_id": query_id,
            }
        }

    async def execute_command(self, command_context):
        yield {"command_response": {"text": command_context["command"]}}

    async def get_plugin_icon(self):
        return {"plugin_icon_file_key": "icon-key", "mime_type": "image/svg+xml"}

    async def get_plugin_readme(self, language="en"):
        return {"plugin_readme_file_key": "readme-key", "language": language}

    async def get_plugin_assets_file(self, file_key):
        if file_key == "missing":
            return {"file_file_key": "", "mime_type": ""}
        return {"file_file_key": "asset-key", "mime_type": "text/plain"}

    async def read_local_file(self, file_key):
        return self.files[file_key]

    async def delete_local_file(self, file_key):
        del self.files[file_key]

    async def call_page_api(self, page_id, endpoint, method, body):
        return {
            "data": {
                "page_id": page_id,
                "endpoint": endpoint,
                "method": method,
                "body": body,
            },
            "error": None,
        }

    async def get_rag_capabilities(self):
        return {"capabilities": ["ingest", "retrieve"]}

    async def rag_ingest_document(self, context_data):
        return {"ingested": context_data["document_id"]}

    async def rag_delete_document(self, kb_id, document_id):
        return {"deleted": [kb_id, document_id]}

    async def rag_on_kb_create(self, kb_id, config):
        return {"created": kb_id, "config": config}

    async def rag_on_kb_delete(self, kb_id):
        return {"deleted_kb": kb_id}

    async def parse_document(self, context_data, file_bytes):
        return {"context": context_data, "text": file_bytes.decode()}


def test_plugin_manager_instances_should_not_share_plugin_state():
    PluginManager.plugins = []
    first = PluginManager(SimpleNamespace())
    second = PluginManager(SimpleNamespace())

    first.plugins.append(_plugin())

    assert second.plugins == []


def test_find_plugin_and_component_lists_respect_include_filters():
    manager = _manager()
    tool = _component("Tool", "lookup")
    command = _component("Command", "admin")
    parser = _component("Parser", "pdf", {"supported_mime_types": ["application/pdf"]})
    manager.plugins = [
        _plugin(name="demo", components=[tool, command, parser]),
        _plugin(name="other", components=[_component("Tool", "skip")]),
    ]

    assert manager.find_plugin("tester", "demo") is manager.plugins[0]
    assert manager.find_plugin("tester", "missing") is None

    tools = asyncio.run(manager.list_tools(include_plugins=["tester/demo"]))
    commands = asyncio.run(manager.list_commands(include_plugins=["tester/demo"]))
    parsers = asyncio.run(manager.list_parsers())

    assert [tool.metadata.name for tool in tools] == ["lookup"]
    assert [command.metadata.name for command in commands] == ["admin"]
    assert parsers[0]["plugin_id"] == "tester/demo"
    assert parsers[0]["supported_mime_types"] == ["application/pdf"]


@pytest.mark.asyncio
async def test_install_plugin_from_file_extracts_manifest_and_replaces_old_version(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    manager = _manager()
    old_plugin = _plugin(name="demo")
    old_plugin._runtime_plugin_handler = FakeHandler(old_plugin)
    manager.plugins = [old_plugin]
    old_path = tmp_path / "data/plugins/tester__demo"
    old_path.mkdir(parents=True)
    (old_path / "old.py").write_text("", encoding="utf-8")

    new_path, author, name, version = await manager.install_plugin_from_file(
        _plugin_zip(version="2.0.0")
    )

    assert (tmp_path / "data/plugins/tester__demo/manifest.yaml").exists()
    assert new_path == "data/plugins/tester__demo"
    assert (author, name, version) == ("tester", "demo", "2.0.0")
    assert manager.plugins == []


@pytest.mark.asyncio
async def test_install_plugin_from_file_rejects_same_version_duplicate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = _manager()
    manager.plugins = [_plugin(name="demo")]

    with pytest.raises(ValueError, match="already exists"):
        await manager.install_plugin_from_file(_plugin_zip(version="1.0.0"))


@pytest.mark.asyncio
async def test_install_plugin_raises_when_dependency_install_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plugin_path = tmp_path / "data/plugins/tester__demo"
    plugin_path.mkdir(parents=True)
    (plugin_path / "requirements.txt").write_text("missing-package\n", encoding="utf-8")
    manager = _manager()

    async def fake_install_from_file(plugin_file):
        return "data/plugins/tester__demo", "tester", "demo", "1.0.0"

    async def fake_install_single_async(dep):
        return 1, 0, "pip could not find package"

    monkeypatch.setattr(manager, "install_plugin_from_file", fake_install_from_file)
    monkeypatch.setattr(
        "langbot_plugin.runtime.plugin.mgr.pkgmgr_helper.install_single_async",
        fake_install_single_async,
    )

    progress = []
    with pytest.raises(RuntimeError, match="pip could not find package"):
        async for item in manager.install_plugin(
            PluginInstallSource.LOCAL,
            {"plugin_file": b"zip"},
        ):
            progress.append(item["current_action"])

    assert progress[0] == "downloading plugin package"
    assert "installing dependencies" in progress
    assert "initializing plugin settings" not in progress
    assert "launching plugin" not in progress


@pytest.mark.asyncio
async def test_register_plugin_initializes_settings_and_refreshes_container():
    manager = _manager()
    control_handler = FakeControlHandler()
    manager.context = SimpleNamespace(control_handler=control_handler)
    plugin = _plugin(
        name="demo",
        components=[_component("Tool", "lookup")],
        status=RuntimeContainerStatus.MOUNTED,
    )
    handler = FakeHandler(plugin)

    await manager.register_plugin(handler, plugin.model_dump())

    registered = manager.plugins[0]
    assert registered._runtime_plugin_handler is handler
    assert registered.install_source == PluginInstallSource.MARKETPLACE.value
    assert registered.install_info == {"plugin_version": "1.0.0"}
    assert registered.status is RuntimeContainerStatus.INITIALIZED
    assert [component.manifest.metadata.name for component in registered.components] == [
        "lookup"
    ]
    assert handler.initialized_with["plugin_config"] == {"api_key": "secret"}


@pytest.mark.asyncio
async def test_call_tool_and_execute_command_delegate_to_connected_plugin():
    manager = _manager()
    plugin = _plugin(
        components=[
            _component("Tool", "lookup"),
            _component("Command", "admin"),
        ]
    )
    plugin._runtime_plugin_handler = FakeHandler(plugin)
    manager.plugins = [plugin]

    tool_response = await manager.call_tool(
        "lookup",
        {"city": "Paris"},
        {"launcher_type": "person"},
        query_id=99,
    )
    command_responses = [
        response
        async for response in manager.execute_command(
            SimpleNamespace(
                command="admin",
                model_dump=lambda mode="json": {"command": "admin"},
            )
        )
    ]

    assert tool_response == {
        "tool_name": "lookup",
        "params": {"city": "Paris"},
        "query_id": 99,
    }
    assert command_responses == [CommandReturn(text="admin")]


@pytest.mark.asyncio
async def test_shutdown_plugin_closes_connection_and_removes_container():
    manager = _manager()
    plugin = _plugin()
    handler = FakeHandler(plugin)
    plugin._runtime_plugin_handler = handler
    manager.plugins = [plugin]
    manager.plugin_handlers = [handler]

    await manager.shutdown_plugin(plugin)

    assert manager.plugins == []
    assert manager.plugin_handlers == []
    assert handler.shutdown_calls == 1
    assert handler.conn.closed is True


@pytest.mark.asyncio
async def test_plugin_resource_and_page_methods_delegate_to_connected_handler():
    manager = _manager()
    plugin = _plugin()
    handler = FakeHandler(plugin)
    plugin._runtime_plugin_handler = handler
    manager.plugins = [plugin]

    assert await manager.get_plugin_icon("tester", "missing") == (b"", "")
    assert await manager.get_plugin_icon("tester", "demo") == (
        b"<svg/>",
        "image/svg+xml",
    )
    assert "icon-key" not in handler.files
    assert await manager.get_plugin_readme("tester", "demo", language="zh") == b"# Demo"
    assert "readme-key" not in handler.files
    assert await manager.get_plugin_assets_file("tester", "demo", "missing") == (
        b"",
        "",
    )
    assert await manager.get_plugin_assets_file("tester", "demo", "asset.txt") == (
        b"asset-bytes",
        "text/plain",
    )
    assert "asset-key" not in handler.files

    page_response = await manager.handle_page_api(
        "tester",
        "demo",
        page_id="settings",
        endpoint="/save",
        method="POST",
        body={"enabled": True},
    )
    assert page_response["data"]["page_id"] == "settings"
    assert page_response["data"]["body"] == {"enabled": True}
    assert await manager.handle_page_api(
        "tester",
        "missing",
        page_id="settings",
        endpoint="/save",
        method="POST",
    ) == {"data": None, "error": "Plugin not found"}


@pytest.mark.asyncio
async def test_knowledge_engine_methods_validate_components_and_delegate_to_handler():
    manager = _manager()
    rag = _component(
        "KnowledgeEngine",
        "kb",
        {
            "creation_schema": [{"name": "api_key"}],
            "retrieval_schema": [{"name": "top_k"}],
        },
    )
    plugin = _plugin(components=[rag])
    plugin._runtime_plugin_handler = FakeHandler(plugin)
    manager.plugins = [plugin]

    engines = await manager.list_knowledge_engines()
    assert engines[0]["plugin_id"] == "tester/demo"
    assert engines[0]["capabilities"] == ["ingest", "retrieve"]
    assert engines[0]["creation_schema"] == {"schema": [{"name": "api_key"}]}
    assert await manager.get_rag_creation_schema("tester", "demo") == {
        "schema": [{"name": "api_key"}]
    }
    assert await manager.get_rag_retrieval_schema("tester", "demo") == {
        "schema": [{"name": "top_k"}]
    }
    assert await manager.rag_ingest_document(
        "tester",
        "demo",
        {"document_id": "doc-1"},
    ) == {"ingested": "doc-1"}
    assert await manager.rag_delete_document("tester", "demo", "kb-1", "doc-1") == {
        "deleted": ["kb-1", "doc-1"]
    }
    assert await manager.rag_on_kb_create(
        "tester",
        "demo",
        "kb-1",
        {"api_key": "secret"},
    ) == {"created": "kb-1", "config": {"api_key": "secret"}}
    assert await manager.rag_on_kb_delete("tester", "demo", "kb-1") == {
        "deleted_kb": "kb-1"
    }

    with pytest.raises(ValueError, match="has no KnowledgeEngine component"):
        manager.plugins = [_plugin(components=[])]
        await manager.rag_ingest_document("tester", "demo", {})


@pytest.mark.asyncio
async def test_parser_methods_validate_components_and_delegate_to_handler():
    manager = _manager()
    parser = _component(
        "Parser",
        "pdf",
        {"supported_mime_types": ["application/pdf"]},
    )
    plugin = _plugin(components=[parser])
    plugin._runtime_plugin_handler = FakeHandler(plugin)
    manager.plugins = [plugin]

    parsers = await manager.list_parsers()
    assert parsers[0]["plugin_id"] == "tester/demo"
    assert parsers[0]["supported_mime_types"] == ["application/pdf"]
    assert await manager.parse_document(
        "tester",
        "demo",
        {"filename": "a.txt"},
        b"hello",
    ) == {"context": {"filename": "a.txt"}, "text": "hello"}

    plugin._runtime_plugin_handler = None
    with pytest.raises(ValueError, match="is not connected"):
        await manager.parse_document("tester", "demo", {}, b"")


@pytest.mark.asyncio
async def test_emit_event_should_report_each_emitting_plugin_once():
    manager = _manager()
    plugin = _plugin()
    plugin._runtime_plugin_handler = FakeHandler(plugin)
    manager.plugins = [plugin]
    event_context = EventContext(
        query_id=1,
        event_name="PersonCommandSent",
        event=PersonCommandSent(
            launcher_type="person",
            launcher_id="launcher",
            sender_id="sender",
            command="demo",
            params=[],
            text_message="/demo",
            is_admin=False,
        ),
    )

    emitted_plugins, _ = await manager.emit_event(event_context)

    assert emitted_plugins == [plugin]
