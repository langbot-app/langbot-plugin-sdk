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
from langbot_plugin.runtime.helper import marketplace as marketplace_helper
from langbot_plugin.runtime.plugin.container import (
    ComponentContainer,
    PluginContainer,
    RuntimeContainerStatus,
)
from langbot_plugin.runtime.plugin.mgr import PluginInstallSource, PluginManager
from langbot_plugin.entities.io.actions.enums import RuntimeToLangBotAction
from langbot_plugin.entities.io.errors import (
    DependencyInstallError,
    DependencyVerificationError,
)


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


class FakeLogBuffer:
    has_active_reader = False

    def __init__(self):
        self.entries = []

    def add_entry(self, level, text):
        self.entries.append((level, text))

    def get_logs(self, limit=200, level=None):
        return [{"limit": limit, "level": level, "text": "ready"}]


class FakeHandler:
    def __init__(self, plugin: PluginContainer):
        self.plugin = plugin
        self.debug_plugin = False
        self.conn = FakeConnection()
        self.stdio_process = None
        self.initialized_with = None
        self.shutdown_calls = 0
        self.diagnostics = []
        self.log_buffer = FakeLogBuffer()
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

    async def notify_plugin_diagnostic(self, diagnostic):
        self.diagnostics.append(diagnostic)
        return {"ok": True}

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

    async def retrieve_knowledge(self, retriever_name, retrieval_context):
        return {
            "retriever_name": retriever_name,
            "retrieval_context": retrieval_context,
        }

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
async def test_notify_plugin_diagnostic_routes_to_target_and_log_buffer():
    manager = _manager()
    plugin = _plugin()
    handler = FakeHandler(plugin)
    plugin._runtime_plugin_handler = handler
    manager.plugins = [plugin]
    diagnostic = {
        "level": "ERROR",
        "code": "deferred_response_delivery_failed",
        "message": "Deferred response delivery failed",
        "plugin": {"author": "tester", "name": "demo"},
        "query": {
            "query_id": 123,
            "event_name": "GroupNormalMessageReceived",
            "stage": "SendResponseBackStage",
        },
        "delivery": {
            "error_type": "ActionFailed",
            "error_message": "retcode=1200",
        },
        "message_chain": {
            "component_types": ["Plain", "Image"],
            "component_count": 2,
        },
    }

    await manager.notify_plugin_diagnostic(diagnostic)

    assert handler.diagnostics == [
        {
            "level": "ERROR",
            "code": "deferred_response_delivery_failed",
            "message": "Deferred response delivery failed",
            "details": {
                "query_id": 123,
                "event_name": "GroupNormalMessageReceived",
                "stage": "SendResponseBackStage",
                "delivery_error": "ActionFailed: retcode=1200",
                "message_chain": {
                    "component_types": ["Plain", "Image"],
                    "component_count": 2,
                },
            },
        }
    ]
    assert handler.log_buffer.entries == [
        (
            "ERROR",
            "[deferred_response_delivery_failed] Deferred response delivery failed"
            " | query_id=123 | event=GroupNormalMessageReceived"
            " | stage=SendResponseBackStage"
            " | delivery_error=ActionFailed: retcode=1200",
        )
    ]


@pytest.mark.asyncio
async def test_notify_plugin_diagnostic_missing_target_only_warns(caplog):
    manager = _manager()
    manager.plugins = []
    caplog.set_level("WARNING")

    await manager.notify_plugin_diagnostic(
        {
            "level": "ERROR",
            "code": "deferred_response_delivery_failed",
            "message": "Deferred response delivery failed",
            "plugin": {"author": "tester", "name": "missing"},
        }
    )

    assert "Plugin diagnostic target not found (tester/missing)" in caplog.text


@pytest.mark.asyncio
async def test_notify_plugin_diagnostic_skips_synthetic_log_with_active_reader():
    manager = _manager()
    plugin = _plugin()
    handler = FakeHandler(plugin)
    handler.log_buffer.has_active_reader = True
    plugin._runtime_plugin_handler = handler
    manager.plugins = [plugin]

    await manager.notify_plugin_diagnostic(
        {
            "level": "ERROR",
            "code": "deferred_response_delivery_failed",
            "message": "Deferred response delivery failed",
            "plugin": {"author": "tester", "name": "demo"},
        }
    )

    assert handler.diagnostics
    assert handler.log_buffer.entries == []


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
async def test_install_plugin_from_file_rejects_same_version_duplicate(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    manager = _manager()
    manager.plugins = [_plugin(name="demo")]

    with pytest.raises(ValueError, match="already exists"):
        await manager.install_plugin_from_file(_plugin_zip(version="1.0.0"))


@pytest.mark.asyncio
async def test_install_plugin_raises_when_dependency_install_fails(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    plugin_path = tmp_path / "data/plugins/tester__demo"
    plugin_path.mkdir(parents=True)
    (plugin_path / "requirements.txt").write_text("missing-package\n", encoding="utf-8")
    manager = _manager()

    async def fake_install_from_file(plugin_file):
        return "data/plugins/tester__demo", "tester", "demo", "1.0.0"

    call_count = {"n": 0}

    async def fake_install_single_async(dep, extra_params=None):
        call_count["n"] += 1
        return 1, 0, "pip could not find package"

    # No real sleeping between retries.
    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(manager, "install_plugin_from_file", fake_install_from_file)
    monkeypatch.setattr(
        "langbot_plugin.runtime.plugin.mgr.pkgmgr_helper.install_single_async",
        fake_install_single_async,
    )
    monkeypatch.setattr(
        "langbot_plugin.runtime.helper.pkgmgr.asyncio.sleep",
        fake_sleep,
    )

    progress = []
    with pytest.raises(DependencyInstallError) as exc_info:
        async for item in manager.install_plugin(
            PluginInstallSource.LOCAL,
            {"plugin_file": b"zip"},
        ):
            progress.append(item["current_action"])

    err = exc_info.value
    assert err.plugin == "tester/demo"
    assert err.failed == ["missing-package"]
    # pip stderr preserved in structured details for debugging.
    assert "pip could not find package" in err.details["missing-package"]
    # install_with_retry must have retried up to max_retries (3) before giving up.
    assert call_count["n"] == 3

    assert progress[0] == "downloading plugin package"
    assert "installing dependencies" in progress
    assert "initializing plugin settings" not in progress
    assert "launching plugin" not in progress


@pytest.mark.asyncio
async def test_install_plugin_raises_verification_error_when_pip_lies(
    tmp_path, monkeypatch
):
    """pip reports success but the dependency is still unsatisfiable."""
    monkeypatch.chdir(tmp_path)
    plugin_path = tmp_path / "data/plugins/tester__demo"
    plugin_path.mkdir(parents=True)
    (plugin_path / "requirements.txt").write_text(
        "langbot-absent-after-install\n", encoding="utf-8"
    )
    manager = _manager()

    async def fake_install_from_file(plugin_file):
        return "data/plugins/tester__demo", "tester", "demo", "1.0.0"

    # pip exits 0 (success) but nothing actually got installed.
    async def fake_install_single_async(dep, extra_params=None):
        return 0, 0, "Successfully installed langbot-absent-after-install"

    monkeypatch.setattr(manager, "install_plugin_from_file", fake_install_from_file)
    monkeypatch.setattr(
        "langbot_plugin.runtime.plugin.mgr.pkgmgr_helper.install_single_async",
        fake_install_single_async,
    )

    with pytest.raises(DependencyVerificationError) as exc_info:
        async for _ in manager.install_plugin(
            PluginInstallSource.LOCAL,
            {"plugin_file": b"zip"},
        ):
            pass

    err = exc_info.value
    assert err.plugin == "tester/demo"
    assert "langbot-absent-after-install" in err.missing
    assert err.version_mismatch == []


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
    assert [
        component.manifest.metadata.name for component in registered.components
    ] == ["lookup"]
    assert handler.initialized_with["plugin_config"] == {"api_key": "secret"}


@pytest.mark.asyncio
async def test_register_debug_plugin_initializes_settings_first():
    manager = _manager()
    control_handler = FakeControlHandler()
    manager.context = SimpleNamespace(control_handler=control_handler)
    plugin = _plugin(name="debug", status=RuntimeContainerStatus.MOUNTED)
    handler = FakeHandler(plugin)
    handler.debug_plugin = True

    await manager.register_plugin(handler, plugin.model_dump(), debug_plugin=True)

    assert [call[0] for call in control_handler.calls] == [
        RuntimeToLangBotAction.INITIALIZE_PLUGIN_SETTINGS,
        RuntimeToLangBotAction.GET_PLUGIN_SETTINGS,
    ]
    assert (
        control_handler.calls[0][1]["install_source"] == PluginInstallSource.DEBUG.value
    )
    assert manager.plugins[0].debug is True


@pytest.mark.asyncio
async def test_register_plugin_requires_control_handler():
    manager = _manager()
    plugin = _plugin(status=RuntimeContainerStatus.MOUNTED)

    with pytest.raises(ValueError, match="Failed to get plugin settings"):
        await manager.register_plugin(FakeHandler(plugin), plugin.model_dump())


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
async def test_call_tool_and_execute_command_return_empty_when_filtered_or_disconnected():
    manager = _manager()
    plugin = _plugin(
        components=[
            _component("Tool", "lookup"),
            _component("Command", "admin"),
        ]
    )
    manager.plugins = [plugin]

    assert (
        await manager.call_tool(
            "lookup",
            {},
            {},
            query_id=1,
            include_plugins=["tester/other"],
        )
        == {}
    )
    assert await manager.call_tool("lookup", {}, {}, query_id=1) == {}
    assert [
        response
        async for response in manager.execute_command(
            SimpleNamespace(
                command="admin",
                model_dump=lambda mode="json": {"command": "admin"},
            )
        )
    ] == []


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
async def test_restart_plugin_debug_skips_relaunch_and_missing_plugin_errors():
    manager = _manager()
    plugin = _plugin(debug=True)
    handler = FakeHandler(plugin)
    plugin._runtime_plugin_handler = handler
    manager.plugins = [plugin]
    manager.plugin_handlers = [handler]

    actions = [
        item["current_action"]
        async for item in manager.restart_plugin("tester", "demo")
    ]

    assert actions == [
        "shutting down plugin",
        "removing plugin container",
        "plugin restarted",
    ]
    assert manager.plugin_run_tasks == []
    assert manager.plugins == []

    with pytest.raises(ValueError, match="Plugin tester/missing not found"):
        async for _ in manager.restart_plugin("tester", "missing"):
            pass


@pytest.mark.asyncio
async def test_delete_plugin_removes_files_and_rejects_debug_plugins(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    manager = _manager()
    plugin_path = tmp_path / "data/plugins/tester__demo"
    plugin_path.mkdir(parents=True)
    (plugin_path / "manifest.yaml").write_text("kind: Plugin\n", encoding="utf-8")
    plugin = _plugin()
    handler = FakeHandler(plugin)
    plugin._runtime_plugin_handler = handler
    manager.plugins = [plugin]
    manager.plugin_handlers = [handler]

    actions = [
        item["current_action"] async for item in manager.delete_plugin("tester", "demo")
    ]

    assert actions == [
        "shutting down plugin",
        "removing plugin container",
        "deleting plugin files",
        "plugin deleted",
    ]
    assert not plugin_path.exists()

    debug = _plugin(debug=True)
    manager.plugins = [debug]
    with pytest.raises(ValueError, match="is a debugging plugin"):
        async for _ in manager.delete_plugin("tester", "demo"):
            pass


@pytest.mark.asyncio
async def test_upgrade_plugin_validates_source_and_reports_up_to_date(monkeypatch):
    manager = _manager()
    debug = _plugin(debug=True)
    manager.plugins = [debug]

    with pytest.raises(ValueError, match="is a debugging plugin"):
        async for _ in manager.upgrade_plugin("tester", "demo"):
            pass

    local = _plugin()
    manager.plugins = [local]
    with pytest.raises(ValueError, match="not installed from marketplace"):
        async for _ in manager.upgrade_plugin("tester", "demo"):
            pass

    marketplace = _plugin()
    marketplace.install_source = PluginInstallSource.MARKETPLACE.value
    manager.plugins = [marketplace]

    async def fake_get_plugin_info(author, name):
        return SimpleNamespace(latest_version="1.0.0")

    monkeypatch.setattr(marketplace_helper, "get_plugin_info", fake_get_plugin_info)

    actions = [
        item["current_action"]
        async for item in manager.upgrade_plugin("tester", "demo")
    ]

    assert actions == ["checking for latest version", "plugin is up to date"]


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
async def test_plugin_logs_and_resource_methods_handle_missing_connections():
    manager = _manager()
    assert await manager.get_plugin_logs("tester", "missing") == []
    assert await manager.get_plugin_readme("tester", "missing") == b""
    assert await manager.get_plugin_assets_file("tester", "missing", "asset.txt") == (
        b"",
        "",
    )

    plugin = _plugin()
    manager.plugins = [plugin]
    assert await manager.get_plugin_logs("tester", "demo") == []
    assert await manager.handle_page_api(
        "tester",
        "demo",
        page_id="settings",
        endpoint="/save",
        method="POST",
    ) == {"data": None, "error": "Plugin is not connected"}

    handler = FakeHandler(plugin)
    plugin._runtime_plugin_handler = handler
    assert await manager.get_plugin_logs("tester", "demo", limit=3, level="INFO") == [
        {"limit": 3, "level": "INFO", "text": "ready"}
    ]


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
async def test_knowledge_engine_errors_and_retrieve_knowledge_delegate():
    manager = _manager()

    with pytest.raises(ValueError, match="Plugin tester/missing not found"):
        await manager.retrieve_knowledge("tester", "missing", "kb", {"query": "hi"})

    plugin = _plugin(components=[_component("KnowledgeEngine", "kb")])
    manager.plugins = [plugin]
    with pytest.raises(ValueError, match="is not connected"):
        await manager.retrieve_knowledge("tester", "demo", "kb", {"query": "hi"})

    handler = FakeHandler(plugin)
    plugin._runtime_plugin_handler = handler
    assert await manager.retrieve_knowledge(
        "tester", "demo", "kb", {"query": "hi"}
    ) == {
        "retriever_name": "kb",
        "retrieval_context": {"query": "hi"},
    }
    assert await manager.get_rag_creation_schema("tester", "missing") == {"schema": []}
    assert await manager.get_rag_retrieval_schema("tester", "missing") == {"schema": []}

    manager.plugins = [_plugin(components=[])]
    with pytest.raises(ValueError, match="has no KnowledgeEngine component"):
        await manager.rag_delete_document("tester", "demo", "kb-1", "doc-1")

    plugin_without_handler = _plugin(components=[_component("KnowledgeEngine", "kb")])
    manager.plugins = [plugin_without_handler]
    with pytest.raises(ValueError, match="is not connected"):
        await manager.rag_on_kb_create("tester", "demo", "kb-1", {})


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
async def test_parser_errors_for_missing_plugin_and_component():
    manager = _manager()

    with pytest.raises(ValueError, match="Plugin tester/missing not found"):
        await manager.parse_document("tester", "missing", {}, b"")

    manager.plugins = [_plugin(components=[])]
    with pytest.raises(ValueError, match="has no Parser component"):
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


@pytest.mark.asyncio
async def test_install_plugin_marketplace_streams_progress_and_launches(monkeypatch):
    manager = _manager()
    control_handler = FakeControlHandler()
    manager.context = SimpleNamespace(control_handler=control_handler)

    async def fake_download_plugin_streaming(author, name, version):
        yield {
            "done": False,
            "downloaded": 5,
            "total": 10,
            "speed": 2,
        }
        yield {"done": True, "data": b"zip"}

    async def fake_install_plugin_from_file(plugin_file):
        assert plugin_file == b"zip"
        return "data/plugins/tester__demo", "tester", "demo", "1.0.0"

    launched = []

    async def fake_launch_plugin(plugin_path):
        launched.append(plugin_path)

    monkeypatch.setattr(
        marketplace_helper,
        "download_plugin_streaming",
        fake_download_plugin_streaming,
    )
    monkeypatch.setattr(
        manager, "install_plugin_from_file", fake_install_plugin_from_file
    )
    monkeypatch.setattr(manager, "launch_plugin", fake_launch_plugin)

    progress = [
        item
        async for item in manager.install_plugin(
            PluginInstallSource.MARKETPLACE,
            {
                "plugin_author": "tester",
                "plugin_name": "demo",
                "plugin_version": "1.0.0",
            },
        )
    ]
    await asyncio.gather(*manager.plugin_run_tasks)

    assert [item["current_action"] for item in progress] == [
        "downloading plugin package",
        "downloading plugin package",
        "installing dependencies",
        "initializing plugin settings",
        "launching plugin",
    ]
    assert progress[1]["metadata"] == {
        "download_current": 5,
        "download_total": 10,
        "download_speed": 2,
    }
    assert control_handler.calls[-1][1]["install_info"] == {
        "plugin_author": "tester",
        "plugin_name": "demo",
        "plugin_version": "1.0.0",
    }
    assert launched == ["data/plugins/tester__demo"]
