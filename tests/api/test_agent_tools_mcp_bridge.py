from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request

import pytest

from langbot_plugin.api.agent_tools import (
    AgentMCPServerConfig,
    AgentRunMCPAccess,
    AgentRunExternalTools,
    AgentRunMCPBridge,
)
from langbot_plugin.api.agent_tools.asset_gateway import AgentAssetGateway
from langbot_plugin.api.agent_tools.daemon import (
    AgentRuntimeDaemonClient,
    AgentRuntimeDaemonHub,
    agent_runtime_daemon_config_from_plugin_config,
    handle_agent_runtime_mcp_payload,
)
from langbot_plugin.api.agent_tools.mcp_config import reverse_tunnel_for_endpoint
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

    async def get_tool_detail(self, **kwargs):
        self.calls.append(("get_tool_detail", kwargs))
        return {
            "name": kwargs["tool_name"],
            "description": "Weather lookup",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        }


def test_agent_run_external_tools_are_annotation_backed() -> None:
    api = FakeRunAPI()
    tools = AgentRunExternalTools(api, _authorized_ctx())

    mcp_tools = {tool["name"]: tool for tool in tools.mcp_tools()}

    assert set(mcp_tools) == {
        "langbot_get_current_event",
        "langbot_list_assets",
        "langbot_history_page",
        "langbot_retrieve_knowledge",
        "langbot_get_tool_detail",
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

    assert {tool["name"] for tool in tools.mcp_tools()} == {
        "langbot_get_current_event",
        "langbot_list_assets",
    }

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
    listed = asyncio.run(
        tools.call_tool(
            "langbot_list_assets",
            {
                "asset_types": ["tools", "mcp_tools"],
                "include_schemas": True,
            },
        )
    )
    tool_detail = asyncio.run(
        tools.call_tool(
            "langbot_get_tool_detail",
            {
                "tool_name": "weather",
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
    assert listed["tools"][0]["tool_name"] == "weather"
    assert "schema" in listed["mcp_tools"][0]
    assert tool_detail["name"] == "weather"
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
        "get_tool_detail",
        {
            "tool_name": "weather",
        },
    )
    assert api.calls[2] == (
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
            assert "langbot_list_assets" in listed_tools
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
                "include_attachments": False,
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
                "include_attachments": False,
            },
        ),
    ]


def test_neutral_mcp_config_and_reverse_tunnel_helpers() -> None:
    config = AgentMCPServerConfig.http(
        name="langbot_agent",
        url="http://127.0.0.1:8765/mcp",
        headers={"Authorization": "Bearer token"},
    )

    assert config.to_dict() == {
        "name": "langbot_agent",
        "transport": "http",
        "url": "http://127.0.0.1:8765/mcp",
        "headers": {"Authorization": "Bearer token"},
    }
    assert config.to_dict(include_type=True)["type"] == "http"
    assert AgentMCPServerConfig.from_dict(config.to_dict()).url == config.url

    tunnel = reverse_tunnel_for_endpoint(config.url)

    assert tunnel.spec == "127.0.0.1:8765:127.0.0.1:8765"
    assert tunnel.ssh_args() == ["-R", "127.0.0.1:8765:127.0.0.1:8765"]


def test_agent_run_mcp_access_returns_remote_http_config_and_tunnel() -> None:
    async def run_probe() -> None:
        api = FakeRunAPI()
        access = AgentRunMCPAccess(
            api,
            _authorized_ctx(),
            location="remote-ssh",
            transport="auto",
        )
        access.start()
        try:
            server = access.server_config
            tunnel = access.reverse_tunnel

            assert server is not None
            assert server.transport == "http"
            assert server.url.endswith("/mcp/http")
            assert tunnel is not None
            assert tunnel.ssh_args()[0] == "-R"
            assert tunnel.local_port == tunnel.remote_port
        finally:
            access.stop()

    asyncio.run(run_probe())


def test_agent_run_mcp_access_disabled_and_gateway_mode() -> None:
    async def run_probe() -> None:
        disabled = AgentRunMCPAccess(FakeRunAPI(), _authorized_ctx(), enabled=False)
        disabled.start()
        assert disabled.server_config is None
        assert disabled.handle is None

        api = FakeRunAPI()
        access = AgentRunMCPAccess(
            api,
            _authorized_ctx(),
            mode="gateway",
            gateway_token_ttl=30,
        )
        access.start()
        try:
            server = access.server_config
            assert server is not None
            assert server.transport == "http"
            assert server.url.endswith("/mcp")
            assert server.headers["Authorization"].startswith("Bearer ")
            assert access.reverse_tunnel is None
        finally:
            access.stop()

        assert access.server_config is None
        assert access.handle is None

    asyncio.run(run_probe())


def test_asset_gateway_uses_run_token_for_stable_mcp_tools() -> None:
    async def run_probe() -> FakeRunAPI:
        api = FakeRunAPI()
        gateway = AgentAssetGateway()
        registration = gateway.register_run(api, _authorized_ctx(), token="token_1")
        try:
            config = registration.http_mcp_server_config(include_token_header=False)

            def call(message: dict, token: str | None = None) -> dict:
                payload = json.dumps(message).encode("utf-8")
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                request = urllib.request.Request(
                    config["url"],
                    data=payload,
                    method="POST",
                    headers=headers,
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))

            tools = await asyncio.to_thread(
                call,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                },
            )
            listed = await asyncio.to_thread(
                call,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "langbot_list_assets",
                        "arguments": {"run_token": "token_1"},
                    },
                },
            )
            detail = await asyncio.to_thread(
                call,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "langbot_get_tool_detail",
                        "arguments": {"tool_name": "weather"},
                    },
                },
                "token_1",
            )
            rejected = await asyncio.to_thread(
                call,
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "langbot_list_assets",
                        "arguments": {"run_token": "bad"},
                    },
                },
            )

            listed_tools = {tool["name"] for tool in tools["result"]["tools"]}
            assert listed_tools >= {
                "langbot_list_assets",
                "langbot_get_tool_detail",
                "langbot_call_tool",
            }
            run_token_schema = next(
                tool
                for tool in tools["result"]["tools"]
                if tool["name"] == "langbot_list_assets"
            )["inputSchema"]["properties"]["run_token"]
            assert run_token_schema["type"] == "string"
            assert (
                listed["result"]["structuredContent"]["tools"][0]["tool_name"]
                == "weather"
            )
            assert detail["result"]["structuredContent"]["name"] == "weather"
            assert rejected["result"]["isError"] is True
            return api
        finally:
            registration.stop()
            gateway.stop()

    api = asyncio.run(run_probe())

    assert api.calls == [
        (
            "get_tool_detail",
            {
                "tool_name": "weather",
            },
        )
    ]


def test_asset_gateway_cleans_expired_registrations() -> None:
    async def run_probe() -> None:
        gateway = AgentAssetGateway()
        registration = gateway.register_run(
            FakeRunAPI(),
            _authorized_ctx(),
            token="expired-token",
            ttl_seconds=30,
        )
        try:
            assert gateway.has_active_registrations() is True
            registration.expires_at = time.monotonic() - 1
            assert gateway.has_active_registrations() is False

            response = gateway.handle_http_mcp_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "langbot_list_assets",
                        "arguments": {"run_token": "expired-token"},
                    },
                }
            )
            assert response["result"]["isError"] is True
            assert "run_token" in response["result"]["content"][0]["text"]
        finally:
            gateway.stop()

    asyncio.run(run_probe())


def test_daemon_config_and_mcp_payload_edges(monkeypatch) -> None:
    monkeypatch.setenv("LANGBOT_AGENT_RUNTIME_DAEMON_ENABLED", "true")
    monkeypatch.setenv("LANGBOT_AGENT_RUNTIME_DAEMON_HOST", "0.0.0.0")
    monkeypatch.setenv("LANGBOT_AGENT_RUNTIME_DAEMON_PORT", "9001")
    monkeypatch.setenv("LANGBOT_AGENT_RUNTIME_DAEMON_TOKEN", "env-token")

    config = agent_runtime_daemon_config_from_plugin_config(
        {"daemon-port": "9100", "daemon-token": "plugin-token"}
    )

    assert config == {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 9100,
        "token": "plugin-token",
    }

    async def run_probe() -> None:
        tools = AgentRunExternalTools(FakeRunAPI(), _authorized_ctx())
        assert await handle_agent_runtime_mcp_payload(tools, []) == {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid request"},
        }
        assert (
            await handle_agent_runtime_mcp_payload(
                tools,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            is None
        )
        missing = await handle_agent_runtime_mcp_payload(
            tools,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "missing/method",
            },
        )
        assert missing["error"]["code"] == -32601

    asyncio.run(run_probe())


def test_agent_runtime_daemon_relay_round_trips_mcp_tools() -> None:
    class ProbeDaemon(AgentRuntimeDaemonClient):
        async def run_job(self, job_id: str, payload: dict) -> None:
            proxy = self.create_mcp_proxy(job_id, request_timeout=5)
            proxy.start()
            try:
                config = proxy.mcp_server()

                def call(message: dict) -> dict:
                    request = urllib.request.Request(
                        config.url,
                        data=json.dumps(message).encode("utf-8"),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(request, timeout=10) as response:
                        return json.loads(response.read().decode("utf-8"))

                tools = await asyncio.to_thread(
                    call,
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    },
                )
                await self.emit_event(job_id, {"type": "probe.tools", "data": tools})
            finally:
                proxy.stop()

    async def run_probe() -> FakeRunAPI:
        api = FakeRunAPI()
        hub = AgentRuntimeDaemonHub()
        await hub.start(host="127.0.0.1", port=0)
        daemon = ProbeDaemon(
            url=hub.endpoint,
            daemon_id="probe",
            reconnect_delay=0.1,
        )
        daemon_task = asyncio.create_task(daemon.run_forever())
        try:
            await hub.wait_for_daemon("probe", timeout=5)
            events = []
            async for event in hub.run_job(
                daemon_id="probe",
                payload={},
                tools=AgentRunExternalTools(api, _authorized_ctx()),
                timeout=10,
            ):
                events.append(event)

            assert events
            listed_tools = {
                tool["name"] for tool in events[0]["data"]["result"]["tools"]
            }
            assert "langbot_history_page" in listed_tools
            assert "langbot_call_tool" in listed_tools
            return api
        finally:
            daemon_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await daemon_task
            await hub.stop()

    asyncio.run(run_probe())
