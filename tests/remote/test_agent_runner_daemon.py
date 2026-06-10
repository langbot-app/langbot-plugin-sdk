from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace

from langbot_plugin.remote.agent_runner.client import default_workspace_key
from langbot_plugin.remote.agent_runner.daemon import (
    GENERIC_RUN_SCHEMA,
    AgentAdapter,
    handle_run_request,
    load_adapters,
    run_subprocess,
)


def test_default_workspace_key_prefers_configured_value() -> None:
    ctx = SimpleNamespace(
        state=SimpleNamespace(conversation={"external.workspace_key": "stored"}),
        conversation=SimpleNamespace(
            workspace_id="workspace",
            bot_id="bot",
            conversation_id="conversation",
            thread_id="thread",
        ),
    )

    assert default_workspace_key(ctx, configured="configured") == "configured"


def test_default_workspace_key_uses_context_identity() -> None:
    ctx = SimpleNamespace(
        state=SimpleNamespace(conversation={}),
        conversation=SimpleNamespace(
            workspace_id="workspace",
            bot_id="bot",
            conversation_id="conversation",
            thread_id="thread",
        ),
    )

    assert default_workspace_key(ctx) == "workspace:bot:conversation:thread"


def test_remote_agent_runner_daemon_runs_custom_sdk_adapter(tmp_path) -> None:
    def build_command(config: dict, resume_session_id: str) -> list[str]:
        script = (
            "import json, pathlib, sys; "
            "assert pathlib.Path('ctx/info.txt').read_text(encoding='utf-8') == 'context'; "
            "print(json.dumps({'stdin': sys.stdin.read(), 'resume': sys.argv[1]}))"
        )
        return [sys.executable, "-c", script, resume_session_id]

    adapter = AgentAdapter(
        name="custom",
        aliases=("custom-agent",),
        schemas=("example.custom.remote_run.v1",),
        display_name="Custom Agent",
        build_command=build_command,
    )
    payload = {
        "schema": GENERIC_RUN_SCHEMA,
        "agent": "custom-agent",
        "workspace_key": "workspace:one",
        "resume_session_id": "session-1",
        "stdin": "hello",
        "timeout": 10,
        "files": [{"path": "ctx/info.txt", "content": "context"}],
    }

    result = asyncio.run(handle_run_request(payload, tmp_path / "workspaces", adapters=(adapter,)))

    assert result["ok"] is True
    output = json.loads(result["stdout"])
    assert output == {"stdin": "hello", "resume": "session-1"}
    assert result["working_directory"].endswith("workspace-one")


def test_remote_agent_runner_daemon_rejects_custom_adapter_file_escape(tmp_path) -> None:
    adapter = AgentAdapter(
        name="custom",
        aliases=(),
        schemas=("example.custom.remote_run.v1",),
        display_name="Custom Agent",
        build_command=lambda config, resume: [sys.executable, "-c", ""],
    )
    payload = {
        "schema": "example.custom.remote_run.v1",
        "workspace_key": "workspace",
        "files": [{"path": "../escape.txt", "content": "bad"}],
    }

    result = asyncio.run(handle_run_request(payload, tmp_path / "workspaces", adapters=(adapter,)))

    assert result == {
        "ok": False,
        "code": "invalid_request",
        "error": "invalid relative file path: ../escape.txt",
    }


def test_load_adapters_from_import_specs(monkeypatch, tmp_path) -> None:
    module_path = tmp_path / "custom_remote.py"
    module_path.write_text(
        "\n".join(
            [
                "from langbot_plugin.remote.agent_runner.daemon import AgentAdapter",
                "",
                "def build_command(config, resume_session_id):",
                "    return ['custom']",
                "",
                "adapter = AgentAdapter(",
                "    name='custom',",
                "    aliases=('custom-alias',),",
                "    schemas=('example.custom.remote_run.v1',),",
                "    display_name='Custom Agent',",
                "    build_command=build_command,",
                ")",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    adapters = load_adapters(["custom_remote:adapter"])

    assert len(adapters) == 1
    assert adapters[0].name == "custom"


def test_run_subprocess_kills_process_on_cancellation(tmp_path) -> None:
    async def exercise() -> None:
        pid_file = tmp_path / "pid.txt"
        script = (
            "import os, pathlib, sys, time; "
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); "
            "time.sleep(60)"
        )
        task = asyncio.create_task(
            run_subprocess(
                [sys.executable, "-c", script, str(pid_file)],
                "",
                60,
                tmp_path,
            )
        )
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        pid = int(pid_file.read_text(encoding="utf-8"))

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("cancelled remote subprocess is still running")

    asyncio.run(exercise())
