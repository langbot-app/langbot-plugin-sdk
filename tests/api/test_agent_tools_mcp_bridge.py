from __future__ import annotations

import asyncio
import json
import os
import urllib.request

import pytest

from langbot_plugin.api.agent_tools import (
    AgentRunExternalTools,
    AgentRunMCPBridge,
)
from langbot_plugin.api.entities.builtin.agent_runner import (
    AgentEventContext,
    AgentInput,
    AgentResources,
    AgentRunContext,
    AgentRuntimeContext,
    AgentTrigger,
    DeliveryContext,
    HistoryPage,
    TranscriptItem,
)
from langbot_plugin.api.entities.builtin.agent_runner.context_access import (
    ContextAccess,
    ContextAPICapabilities,
)


def _ctx() -> AgentRunContext:
    return AgentRunContext(
        run_id="run_1",
        trigger=AgentTrigger(type="message.received"),
        event=AgentEventContext(
            event_id="evt_1",
            event_type="message.received",
            source="host_adapter",
        ),
        input=AgentInput(text="hello from im"),
        delivery=DeliveryContext(surface="platform"),
        resources=AgentResources(),
        runtime=AgentRuntimeContext(),
        config={},
    )


def _authorized_ctx() -> AgentRunContext:
    ctx = _ctx()
    ctx.resources = AgentResources.model_validate(
        {
            "knowledge_bases": [{"kb_id": "kb_1"}],
            "tools": [{"tool_name": "weather"}],
        }
    )
    ctx.context = ContextAccess(
        available_apis=ContextAPICapabilities(history_page=True)
    )
    return ctx


class FakeRunAPI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def history_page(self, **kwargs):
        self.calls.append(("history_page", kwargs))
        return HistoryPage(
            items=[
                TranscriptItem(
                    transcript_id="transcript_1",
                    event_id="event_1",
                    role="user",
                    content="older",
                )
            ],
            has_more=False,
        )

    async def retrieve_knowledge(self, **kwargs):
        self.calls.append(("retrieve_knowledge", kwargs))
        return [{"content": f"kb:{kwargs['query_text']}"}]

    async def call_tool(self, **kwargs):
        self.calls.append(("call_tool", kwargs))
        return {"ok": True, "tool_name": kwargs["tool_name"]}


def test_agent_run_external_tools_are_annotation_backed() -> None:
    api = FakeRunAPI()
    tools = AgentRunExternalTools(api, _authorized_ctx())

    mcp_tools = {tool["name"]: tool for tool in tools.mcp_tools()}

    assert set(mcp_tools) == {
        "langbot_get_current_event",
        "langbot_history_page",
        "langbot_retrieve_knowledge",
        "langbot_call_tool",
    }
    assert (
        mcp_tools["langbot_retrieve_knowledge"]["inputSchema"]["properties"]["kb_id"][
            "type"
        ]
        == "string"
    )
    assert mcp_tools["langbot_get_current_event"]["annotations"]["readOnlyHint"] is True


def test_agent_run_external_tools_are_run_authorization_filtered() -> None:
    api = FakeRunAPI()
    tools = AgentRunExternalTools(api, _ctx())

    assert {tool["name"] for tool in tools.mcp_tools()} == {"langbot_get_current_event"}

    with pytest.raises(ValueError, match="Unknown LangBot external tool"):
        asyncio.run(tools.call_tool("langbot_history_page", {"limit": 1}))


def test_agent_run_external_tools_call_agent_run_api() -> None:
    api = FakeRunAPI()
    tools = AgentRunExternalTools(api, _authorized_ctx())

    event = asyncio.run(tools.call_tool("langbot_get_current_event"))
    retrieved = asyncio.run(
        tools.call_tool(
            "langbot_retrieve_knowledge",
            {
                "kb_id": "kb_1",
                "query_text": "hello",
                "top_k": 2,
            },
        )
    )
    tool_result = asyncio.run(
        tools.call_tool(
            "langbot_call_tool",
            {
                "tool_name": "weather",
                "parameters": {"city": "Shanghai"},
            },
        )
    )

    assert event["input"]["text"] == "hello from im"
    assert retrieved == [{"content": "kb:hello"}]
    assert tool_result == {"ok": True, "tool_name": "weather"}
    assert api.calls[0] == (
        "retrieve_knowledge",
        {
            "kb_id": "kb_1",
            "query_text": "hello",
            "top_k": 2,
            "filters": {},
        },
    )
    assert api.calls[1] == (
        "call_tool",
        {
            "tool_name": "weather",
            "parameters": {"city": "Shanghai"},
        },
    )


def test_mcp_stdio_proxy_round_trips_history_rag_and_tool_actions() -> None:
    async def run_probe() -> FakeRunAPI:
        api = FakeRunAPI()
        bridge = AgentRunMCPBridge.from_run_api(api, _authorized_ctx())
        bridge.start()
        try:
            config = bridge.mcp_server_config()
            messages = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "langbot_history_page",
                        "arguments": {"limit": 3, "direction": "backward"},
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "langbot_retrieve_knowledge",
                        "arguments": {
                            "kb_id": "kb_1",
                            "query_text": "stdio",
                            "top_k": 2,
                        },
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "langbot_call_tool",
                        "arguments": {
                            "tool_name": "weather",
                            "parameters": {"city": "Shanghai"},
                        },
                    },
                },
            ]
            stdin = (
                "\n".join(json.dumps(item, ensure_ascii=False) for item in messages)
                + "\n"
            )
            process = await asyncio.create_subprocess_exec(
                config["command"],
                *config["args"],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **config["env"]},
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin.encode("utf-8")), timeout=20
            )
            assert process.returncode == 0, stderr.decode("utf-8", errors="replace")

            responses = [
                json.loads(line)
                for line in stdout.decode("utf-8").splitlines()
                if line.strip()
            ]
            listed_tools = {tool["name"] for tool in responses[1]["result"]["tools"]}
            assert "langbot_history_page" in listed_tools
            assert (
                responses[2]["result"]["structuredContent"]["items"][0]["content"]
                == "older"
            )
            assert responses[2]["result"]["content"][0]["text"].startswith('{"items"')
            assert responses[3]["result"]["structuredContent"]["result"] == [
                {"content": "kb:stdio"}
            ]
            assert responses[4]["result"]["structuredContent"] == {
                "ok": True,
                "tool_name": "weather",
            }
            return api
        finally:
            bridge.stop()

    api = asyncio.run(run_probe())

    assert api.calls == [
        (
            "history_page",
            {
                "conversation_id": None,
                "before_cursor": None,
                "after_cursor": None,
                "limit": 3,
                "direction": "backward",
                "include_artifacts": False,
            },
        ),
        (
            "retrieve_knowledge",
            {
                "kb_id": "kb_1",
                "query_text": "stdio",
                "top_k": 2,
                "filters": {},
            },
        ),
        (
            "call_tool",
            {
                "tool_name": "weather",
                "parameters": {"city": "Shanghai"},
            },
        ),
    ]


def test_mcp_http_endpoint_round_trips_langbot_actions() -> None:
    async def run_probe() -> FakeRunAPI:
        api = FakeRunAPI()
        bridge = AgentRunMCPBridge.from_run_api(api, _authorized_ctx())
        bridge.start()
        try:
            config = bridge.http_mcp_server_config()

            def call(message: dict) -> dict:
                payload = json.dumps(message).encode("utf-8")
                request = urllib.request.Request(
                    config["url"],
                    data=payload,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        **config["headers"],
                    },
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))

            initialized = await asyncio.to_thread(
                call,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                },
            )
            tools = await asyncio.to_thread(
                call,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )
            history = await asyncio.to_thread(
                call,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "langbot_history_page",
                        "arguments": {"limit": 2},
                    },
                },
            )

            assert initialized["result"]["serverInfo"]["name"] == "langbot-agent"
            assert {tool["name"] for tool in tools["result"]["tools"]} >= {
                "langbot_history_page",
                "langbot_retrieve_knowledge",
                "langbot_call_tool",
            }
            assert (
                history["result"]["structuredContent"]["items"][0]["content"] == "older"
            )
            return api
        finally:
            bridge.stop()

    api = asyncio.run(run_probe())

    assert api.calls == [
        (
            "history_page",
            {
                "conversation_id": None,
                "before_cursor": None,
                "after_cursor": None,
                "limit": 2,
                "direction": "backward",
                "include_artifacts": False,
            },
        ),
    ]
