"""Event admission through real plugin subprocesses and production stdio RPC."""

import asyncio
import json
import os
import sys

import pytest
import yaml

from langbot_plugin.api.entities.context import EventContext
from langbot_plugin.api.entities.events import PersonCommandSent
from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction
from langbot_plugin.runtime.context import RuntimeContext
from langbot_plugin.runtime.io.connections.stdio import StdioConnection
from langbot_plugin.runtime.io.handlers.plugin import PluginConnectionHandler
from langbot_plugin.runtime.plugin.container import (
    PluginContainer,
    RuntimeContainerStatus,
)
from langbot_plugin.runtime.plugin.mgr import PluginManager


class RecordingStdio(StdioConnection):
    """Observe actual outgoing wire frames without replacing the transport."""

    def __init__(self, process):
        super().__init__(process.stdout, process.stdin, process)
        self.event_frames = 0

    async def send(self, message):
        if json.loads(message).get("action") == "emit_event":
            self.event_frames += 1
        await super().send(message)


def write_plugin(root, name, kind):
    root.mkdir()
    (root / "components").mkdir()
    manifest = {
        "apiVersion": "v1",
        "kind": "Plugin",
        "metadata": {
            "author": "tester",
            "name": name,
            "version": "1.0.0",
            "label": {"en_US": name},
        },
        "spec": {"components": {kind: {"fromFiles": ["components/probe.yaml"]}}},
        "execution": {"python": {"path": "main.py", "attr": "Probe"}},
    }
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    (root / "main.py").write_text(
        "from langbot_plugin.api.definition.plugin import BasePlugin\n"
        "class Probe(BasePlugin):\n    pass\n"
    )
    component = {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": {"name": "probe", "label": {"en_US": "Probe"}},
        "spec": {},
        "execution": {"python": {"path": "probe.py", "attr": "Probe"}},
    }
    (root / "components/probe.yaml").write_text(yaml.safe_dump(component))
    if kind == "EventListener":
        source = """from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities.events import PersonCommandSent
class Probe(EventListener):
    async def initialize(self):
        @self.handler(PersonCommandSent)
        async def handle(ctx):
            if ctx.event.command == "fail":
                raise RuntimeError("real listener fault")
            ctx.event.text_message += ":NAME"
            if ctx.event.command == "stop" and "NAME" == "first":
                ctx.is_prevent_postorder = True
""".replace("NAME", name)
    else:
        module = "tool.tool" if kind == "Tool" else "command.command"
        source = (
            f"from langbot_plugin.api.definition.components.{module} import {kind}\n"
            f"class Probe({kind}):\n"
            "    async def call(self, params, session, query_id):\n"
            "        return 'tool-ok'\n"
        )
    (root / "components/probe.py").write_text(source)


@pytest.mark.asyncio
async def test_event_dispatch_real_workers(tmp_path):
    context = RuntimeContext()
    context.ws_debug_port = 0
    manager = PluginManager(context)
    context.plugin_mgr = manager
    manager.plugins = []
    resources = []
    tasks = []
    wires = {}
    try:
        for name, kind in [
            ("tool", "Tool"),
            ("command", "Command"),
            ("first", "EventListener"),
            ("second", "EventListener"),
        ]:
            root = tmp_path / name
            write_plugin(root, name, kind)
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "langbot_plugin.cli.__init__",
                "run",
                "-s",
                "--prod",
                cwd=root,
                env=dict(
                    os.environ,
                    LANGBOT_PLUGIN_REGISTRATION_CAPABILITY="e2e-only-capability",
                    LANGBOT_PLUGIN_FILE_STORAGE_DIR=str(root / "transfer"),
                    PYTHONUNBUFFERED="1",
                ),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            resources.append((process, None))
            wire = RecordingStdio(process)
            registration = json.loads(await asyncio.wait_for(wire.receive(), 20))
            assert registration["action"] == "register_plugin"
            plugin = PluginContainer.from_dict(registration["data"]["plugin_container"])
            await wire.send(
                json.dumps(
                    {
                        "seq_id": registration["seq_id"],
                        "code": 0,
                        "message": "ok",
                        "data": {},
                    }
                )
            )
            handler = PluginConnectionHandler(
                wire, context, process, file_storage_dir=str(root / "host-transfer")
            )
            resources[-1] = (process, handler)
            tasks.append(asyncio.create_task(handler.run()))
            await handler.call_action(
                RuntimeToPluginAction.INITIALIZE_PLUGIN,
                {
                    "plugin_settings": {
                        "enabled": True,
                        "priority": 1,
                        "plugin_config": {},
                    }
                },
            )
            plugin.enabled = True
            plugin.status = RuntimeContainerStatus.INITIALIZED
            plugin._runtime_plugin_handler = handler
            manager.plugins.append(plugin)
            wires[name] = wire

        def event(command="demo"):
            return EventContext(
                query_id=1,
                query_uuid="rpc-e2e-query",
                event_name="PersonCommandSent",
                event=PersonCommandSent(
                    launcher_type="person",
                    launcher_id="local",
                    sender_id="local",
                    command=command,
                    params=[],
                    text_message="/demo",
                    is_admin=False,
                ),
            )

        emitted, result, _ = await manager.emit_event(event())
        assert [p.manifest.metadata.name for p in emitted] == ["first", "second"]
        assert result.event.text_message == "/demo:first:second"
        assert result.query_uuid == "rpc-e2e-query"
        assert {n: w.event_frames for n, w in wires.items()} == {
            "tool": 0,
            "command": 0,
            "first": 1,
            "second": 1,
        }
        emitted, result, _ = await manager.emit_event(event("stop"))
        assert [p.manifest.metadata.name for p in emitted] == ["first"]
        assert result.event.text_message == "/demo:first"
        emitted, result, _ = await manager.emit_event(
            event(), include_plugins=["tester/tool", "tester/command", "tester/second"]
        )
        assert [p.manifest.metadata.name for p in emitted] == ["second"]
        assert result.event.text_message == "/demo:second"
        before = {n: w.event_frames for n, w in wires.items()}
        emitted, _, _ = await manager.emit_event(event(), include_plugins=[])
        assert emitted == []
        assert before == {n: w.event_frames for n, w in wires.items()}
        with pytest.raises(Exception, match="real listener fault"):
            await manager.emit_event(event("fail"))
        assert wires["second"].event_frames == before["second"]
        assert wires["tool"].event_frames == wires["command"].event_frames == 0
        print("REAL_RPC_VERIFIED", {n: w.event_frames for n, w in wires.items()})
    finally:
        for process, handler in resources:
            if handler is not None:
                await handler.close()
            if process.returncode is None:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 10)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            if handler is None and process.stderr is not None:
                print((await process.stderr.read()).decode())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
