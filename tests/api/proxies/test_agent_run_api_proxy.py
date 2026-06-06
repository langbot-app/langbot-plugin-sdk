"""Tests for AgentRunAPIProxy restricted API surface and permission validation.

These tests verify that AgentRunAPIProxy:
1. Only exposes APIs explicitly authorized through ctx.resources
2. Validates resource access before execution
3. Does NOT expose unrestricted global APIs
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from langbot_plugin.api.proxies.agent_run_api import (
    AgentRunAPIProxy,
    PermissionDeniedError,
)
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.api.entities.builtin.provider.message import Message
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.resources import (
    AgentResources,
    ModelResource,
    ToolResource,
    KnowledgeBaseResource,
    StorageResource,
    FileResource,
)
from langbot_plugin.api.entities.builtin.agent_runner.runtime import AgentRuntimeContext
from langbot_plugin.api.entities.builtin.agent_runner.trigger import AgentTrigger
from langbot_plugin.api.entities.builtin.agent_runner.input import AgentInput
from langbot_plugin.api.entities.builtin.agent_runner.event import AgentEventContext
from langbot_plugin.api.entities.builtin.agent_runner.delivery import DeliveryContext
from langbot_plugin.api.entities.builtin.agent_runner.context_access import (
    ContextAccess,
    ContextAPICapabilities,
)


class MockHandler:
    """Mock Handler for testing AgentRunAPIProxy."""

    def __init__(self):
        self.call_action_mock = AsyncMock()
        self.call_action_generator_mock = AsyncMock()

    async def call_action(
        self, action: PluginToRuntimeAction, data: dict, timeout: float = 120
    ):
        """Mock call_action that returns expected response."""
        return await self.call_action_mock(action, data, timeout)

    def call_action_generator(
        self, action: PluginToRuntimeAction, data: dict, timeout: float = 120
    ):
        """Mock call_action_generator - returns an async generator."""
        return self.call_action_generator_mock(action, data, timeout)


def create_mock_context(
    run_id: str = "test_run",
    deadline_at: float | None = None,
    models: list[dict] | None = None,
    tools: list[dict] | None = None,
    knowledge_bases: list[dict] | None = None,
    storage: dict | None = None,
    files: list[dict] | None = None,
    prompt_get: bool = False,
    available_apis: ContextAPICapabilities | None = None,
) -> AgentRunContext:
    """Create a mock AgentRunContext for testing."""
    if available_apis is None:
        available_apis = ContextAPICapabilities(
            history_page=True,
            history_search=True,
            event_get=True,
            event_page=True,
            artifact_metadata=True,
            artifact_read=True,
            state=True,
            storage=True,
            prompt_get=prompt_get,
        )

    return AgentRunContext(
        run_id=run_id,
        trigger=AgentTrigger(type="user_message"),
        event=AgentEventContext(
            event_id="test_event",
            event_type="message.received",
            source="test",
        ),
        input=AgentInput(content="test input"),
        delivery=DeliveryContext(surface="test"),
        context=ContextAccess(
            available_apis=available_apis,
        ),
        runtime=AgentRuntimeContext(deadline_at=deadline_at),
        resources=AgentResources(
            models=[ModelResource.model_validate(m) for m in (models or [])],
            tools=[ToolResource.model_validate(t) for t in (tools or [])],
            knowledge_bases=[
                KnowledgeBaseResource.model_validate(kb)
                for kb in (knowledge_bases or [])
            ],
            storage=StorageResource.model_validate(
                storage or {"plugin_storage": False, "workspace_storage": False}
            ),
            files=[FileResource.model_validate(f) for f in (files or [])],
        ),
    )


class TestAgentRunAPIProxyRestrictedAPISurface:
    """Tests to verify AgentRunAPIProxy does NOT expose unrestricted global APIs."""

    def test_does_not_expose_get_bots(self):
        """AgentRunAPIProxy should NOT have get_bots method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "get_bots"), (
            "AgentRunAPIProxy should not expose get_bots (use AgentRunResult.action_requested)"
        )

    def test_does_not_expose_send_message(self):
        """AgentRunAPIProxy should NOT have send_message method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "send_message"), (
            "AgentRunAPIProxy should not expose send_message (use AgentRunResult.action_requested)"
        )

    def test_does_not_expose_list_tools(self):
        """AgentRunAPIProxy should NOT have list_tools method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "list_tools"), (
            "AgentRunAPIProxy should not expose list_tools (use get_allowed_tools() instead)"
        )

    def test_exposes_get_tool_detail_with_validation(self):
        """AgentRunAPIProxy exposes get_tool_detail() for authorized tool schemas."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, "get_tool_detail"), (
            "AgentRunAPIProxy should expose get_tool_detail() for authorized function calling"
        )

    def test_does_not_expose_vector_upsert(self):
        """AgentRunAPIProxy should NOT have vector_upsert method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "vector_upsert"), (
            "AgentRunAPIProxy should not expose vector_upsert (no vector resources defined)"
        )

    def test_does_not_expose_vector_search(self):
        """AgentRunAPIProxy should NOT have vector_search method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "vector_search"), (
            "AgentRunAPIProxy should not expose vector_search (no vector resources defined)"
        )

    def test_does_not_expose_invoke_embedding(self):
        """AgentRunAPIProxy should NOT have invoke_embedding method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "invoke_embedding"), (
            "AgentRunAPIProxy should not expose invoke_embedding (no embedding model resources defined)"
        )

    def test_does_not_expose_get_llm_models(self):
        """AgentRunAPIProxy should NOT have get_llm_models method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "get_llm_models"), (
            "AgentRunAPIProxy should not expose get_llm_models (use get_allowed_models() instead)"
        )

    def test_does_not_expose_list_knowledge_bases(self):
        """AgentRunAPIProxy should NOT have list_knowledge_bases method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "list_knowledge_bases"), (
            "AgentRunAPIProxy should not expose list_knowledge_bases (use get_allowed_knowledge_bases() instead)"
        )

    def test_does_not_expose_get_config_file(self):
        """AgentRunAPIProxy should NOT have get_config_file method."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "get_config_file"), (
            "AgentRunAPIProxy should not expose get_config_file (use get_file() with file access validation)"
        )

    def test_exposes_get_file_with_validation(self):
        """AgentRunAPIProxy exposes get_file() with file access validation."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, "get_file"), (
            "AgentRunAPIProxy should expose get_file() for authorized file access"
        )

    def test_exposes_allowed_resource_helpers(self):
        """AgentRunAPIProxy exposes resource helper methods."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, "get_allowed_models")
        assert hasattr(proxy, "get_allowed_tools")
        assert hasattr(proxy, "get_allowed_knowledge_bases")
        assert hasattr(proxy, "get_allowed_files")

    def test_exposes_storage_methods_with_validation(self):
        """AgentRunAPIProxy exposes storage methods with permission validation."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, "set_plugin_storage")
        assert hasattr(proxy, "get_plugin_storage")
        assert hasattr(proxy, "delete_plugin_storage")
        assert hasattr(proxy, "set_workspace_storage")
        assert hasattr(proxy, "get_workspace_storage")
        assert hasattr(proxy, "delete_workspace_storage")

    def test_exposes_version_api(self):
        """AgentRunAPIProxy exposes get_langbot_version (no authorization needed)."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, "get_langbot_version")

    def test_exposes_prompt_api_with_availability_validation(self):
        """AgentRunAPIProxy exposes run-scoped prompt access."""
        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, "get_prompt")


class TestAgentRunAPIProxyResourceValidation:
    """Tests for resource validation in AgentRunAPIProxy."""

    @pytest.mark.anyio
    async def test_invoke_llm_with_authorized_model(self):
        """invoke_llm succeeds when model is in ctx.resources.models."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "message": {"role": "assistant", "content": "Hello back"}
        }

        ctx = create_mock_context(
            run_id="run_llm_test", models=[{"model_id": "model_001"}]
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        messages = [Message(role="user", content="Hello")]
        await proxy.invoke_llm("model_001", messages)

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert data["run_id"] == "run_llm_test"
        assert data["llm_model_uuid"] == "model_001"

    @pytest.mark.anyio
    async def test_invoke_llm_with_unauthorized_model_raises_error(self):
        """invoke_llm raises PermissionDeniedError when model is NOT authorized."""
        mock_handler = MockHandler()

        ctx = create_mock_context(
            run_id="run_unauth",
            models=[{"model_id": "model_001"}],  # Only model_001 is authorized
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        messages = [Message(role="user", content="Hello")]

        with pytest.raises(PermissionDeniedError) as exc_info:
            await proxy.invoke_llm("model_999", messages)  # model_999 is NOT authorized

        assert "model_999" in str(exc_info.value)
        assert "not authorized" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_call_tool_with_authorized_tool(self):
        """call_tool succeeds when tool is in ctx.resources.tools."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"result": {"status": "success"}}

        ctx = create_mock_context(
            run_id="run_tool_test", tools=[{"tool_name": "web_search"}]
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.call_tool("web_search", {"query": "hello"})

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert data["run_id"] == "run_tool_test"
        assert data["tool_name"] == "web_search"
        assert "query_id" not in data

    @pytest.mark.anyio
    async def test_call_tool_with_unauthorized_tool_raises_error(self):
        """call_tool raises PermissionDeniedError when tool is NOT authorized."""
        mock_handler = MockHandler()

        ctx = create_mock_context(
            run_id="run_unauth",
            tools=[{"tool_name": "web_search"}],  # Only web_search is authorized
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        with pytest.raises(PermissionDeniedError) as exc_info:
            await proxy.call_tool(
                "image_gen", {"prompt": "hello"}
            )  # image_gen NOT authorized

        assert "image_gen" in str(exc_info.value)
        assert "not authorized" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_get_prompt_requires_available_api(self):
        """get_prompt is rejected unless Host exposed prompt_get for this run."""
        proxy = AgentRunAPIProxy(
            ctx=create_mock_context(available_apis=ContextAPICapabilities()),
            plugin_runtime_handler=MockHandler(),
        )

        with pytest.raises(PermissionDeniedError) as exc_info:
            await proxy.get_prompt()

        assert "prompt_get" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_get_prompt_with_available_api(self):
        """get_prompt calls the run-scoped Host prompt API."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "prompt": [{"role": "system", "content": "Host prompt"}],
        }
        ctx = create_mock_context(run_id="run_prompt_test", prompt_get=True)
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        prompt = await proxy.get_prompt()

        assert prompt == [{"role": "system", "content": "Host prompt"}]
        action, data, _timeout = mock_handler.call_action_mock.call_args[0]
        assert action == PluginToRuntimeAction.PROMPT_GET
        assert data == {"run_id": "run_prompt_test"}

    @pytest.mark.anyio
    async def test_retrieve_knowledge_with_authorized_kb(self):
        """retrieve_knowledge succeeds when kb is in ctx.resources.knowledge_bases."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"results": [{"text": "doc1"}]}

        ctx = create_mock_context(
            run_id="run_kb_test", knowledge_bases=[{"kb_id": "kb_001"}]
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.retrieve_knowledge("kb_001", "search query")

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert data["run_id"] == "run_kb_test"
        assert data["kb_id"] == "kb_001"
        assert "query_id" not in data

    @pytest.mark.anyio
    async def test_retrieve_knowledge_with_unauthorized_kb_raises_error(self):
        """retrieve_knowledge raises PermissionDeniedError when kb is NOT authorized."""
        mock_handler = MockHandler()

        ctx = create_mock_context(
            run_id="run_unauth",
            knowledge_bases=[{"kb_id": "kb_001"}],  # Only kb_001 is authorized
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        with pytest.raises(PermissionDeniedError) as exc_info:
            await proxy.retrieve_knowledge(
                "kb_999", "search query"
            )  # kb_999 NOT authorized

        assert "kb_999" in str(exc_info.value)
        assert "not authorized" in str(exc_info.value)


class TestAgentRunAPIProxyAvailableAPIGate:
    """Run-scoped pull APIs must fail locally when Host did not expose them."""

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("method_name", "capability_name", "args"),
        [
            ("history_page", "history_page", ()),
            ("history_search", "history_search", ("query",)),
            ("event_get", "event_get", ("event_1",)),
            ("event_page", "event_page", ()),
            ("artifact_metadata", "artifact_metadata", ("artifact_1",)),
            ("artifact_read", "artifact_read", ("artifact_1",)),
            ("state_get", "state", ("conversation", "external.key")),
            ("state_set", "state", ("conversation", "external.key", {"v": 1})),
            ("state_delete", "state", ("conversation", "external.key")),
            ("state_list", "state", ("conversation",)),
        ],
    )
    async def test_pull_api_requires_available_api_before_forwarding(
        self,
        method_name: str,
        capability_name: str,
        args: tuple,
    ):
        mock_handler = MockHandler()
        proxy = AgentRunAPIProxy(
            ctx=create_mock_context(available_apis=ContextAPICapabilities()),
            plugin_runtime_handler=mock_handler,
        )

        with pytest.raises(PermissionDeniedError) as exc_info:
            await getattr(proxy, method_name)(*args)

        assert capability_name in str(exc_info.value)
        mock_handler.call_action_mock.assert_not_called()
        mock_handler.call_action_generator_mock.assert_not_called()


class TestAgentRunAPIProxyNoQueryId:
    """AgentRunAPIProxy does not expose or forward query_id."""

    def test_query_id_property_is_not_exposed(self):
        ctx = create_mock_context(run_id="test_run")
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert not hasattr(proxy, "query_id")

    @pytest.mark.anyio
    async def test_retrieve_knowledge_does_not_send_query_id(self):
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"results": []}

        ctx = create_mock_context(
            run_id="run_no_query",
            knowledge_bases=[{"kb_id": "kb_001"}],
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.retrieve_knowledge("kb_001", "search query")

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert "query_id" not in data

    @pytest.mark.anyio
    async def test_call_tool_does_not_send_query_id(self):
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"result": {}}

        ctx = create_mock_context(
            run_id="run_no_query",
            tools=[{"tool_name": "test_tool"}],
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.call_tool("test_tool", {"param": "value"})

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert "query_id" not in data


class TestAgentRunAPIProxyStoragePermission:
    """Tests for storage permission validation in AgentRunAPIProxy."""

    @pytest.mark.anyio
    async def test_plugin_storage_when_disabled_raises_error(self):
        """set_plugin_storage raises PermissionDeniedError when storage is disabled."""
        mock_handler = MockHandler()

        ctx = create_mock_context(
            run_id="run_storage",
            storage={"plugin_storage": False, "workspace_storage": False},  # Disabled
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        with pytest.raises(PermissionDeniedError) as exc_info:
            await proxy.set_plugin_storage("key", b"value")

        assert "plugin storage" in str(exc_info.value).lower()
        assert "not authorized" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_plugin_storage_when_enabled_succeeds(self):
        """set_plugin_storage succeeds when storage is enabled."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {}

        ctx = create_mock_context(
            run_id="run_storage",
            storage={
                "plugin_storage": True,
                "workspace_storage": False,
            },  # Plugin storage enabled
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.set_plugin_storage("key", b"value")

        # Should have called the action
        assert mock_handler.call_action_mock.called

    @pytest.mark.anyio
    async def test_workspace_storage_when_disabled_raises_error(self):
        """set_workspace_storage raises PermissionDeniedError when storage is disabled."""
        mock_handler = MockHandler()

        ctx = create_mock_context(
            run_id="run_storage",
            storage={"plugin_storage": False, "workspace_storage": False},  # Disabled
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        with pytest.raises(PermissionDeniedError) as exc_info:
            await proxy.set_workspace_storage("key", b"value")

        assert "workspace storage" in str(exc_info.value).lower()
        assert "not authorized" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_workspace_storage_when_enabled_succeeds(self):
        """set_workspace_storage succeeds when storage is enabled."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {}

        ctx = create_mock_context(
            run_id="run_storage",
            storage={
                "plugin_storage": False,
                "workspace_storage": True,
            },  # Workspace storage enabled
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.set_workspace_storage("key", b"value")

        # Should have called the action
        assert mock_handler.call_action_mock.called

    @pytest.mark.anyio
    async def test_get_plugin_storage_when_disabled_raises_error(self):
        """get_plugin_storage raises PermissionDeniedError when storage is disabled."""
        mock_handler = MockHandler()

        ctx = create_mock_context(
            run_id="run_storage",
            storage={"plugin_storage": False, "workspace_storage": False},
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        with pytest.raises(PermissionDeniedError) as exc_info:
            await proxy.get_plugin_storage("key")

        assert "plugin storage" in str(exc_info.value).lower()


class TestAgentRunAPIProxyFileAccess:
    """Tests for file access validation in AgentRunAPIProxy."""

    @pytest.mark.anyio
    async def test_get_file_with_authorized_file(self):
        """get_file succeeds when file is in ctx.resources.files."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"file_base64": "SGVsbG8="}

        ctx = create_mock_context(
            run_id="run_file_test", files=[{"file_id": "file_001"}]
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        result = await proxy.get_file("file_001")

        assert result == b"Hello"  # base64 decoded

    @pytest.mark.anyio
    async def test_get_file_with_unauthorized_file_raises_error(self):
        """get_file raises PermissionDeniedError when file is NOT authorized."""
        mock_handler = MockHandler()

        ctx = create_mock_context(
            run_id="run_unauth",
            files=[{"file_id": "file_001"}],  # Only file_001 is authorized
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        with pytest.raises(PermissionDeniedError) as exc_info:
            await proxy.get_file("file_999")  # file_999 NOT authorized

        assert "file_999" in str(exc_info.value)
        assert "not authorized" in str(exc_info.value)


class TestAgentRunAPIProxyTimeoutValues:
    """Tests for timeout values in AgentRunAPIProxy."""

    @pytest.mark.anyio
    async def test_invoke_llm_default_timeout(self):
        """invoke_llm default timeout is 120 seconds."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "message": {"role": "assistant", "content": "Hello"}
        }

        ctx = create_mock_context(models=[{"model_id": "model_001"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.invoke_llm("model_001", [Message(role="user", content="Hello")])

        call_args = mock_handler.call_action_mock.call_args
        timeout = call_args[0][2]

        assert timeout == 120.0

    @pytest.mark.anyio
    async def test_invoke_llm_custom_timeout(self):
        """invoke_llm custom timeout is passed correctly."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "message": {"role": "assistant", "content": "Hello"}
        }

        ctx = create_mock_context(models=[{"model_id": "model_001"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.invoke_llm(
            "model_001", [Message(role="user", content="Hello")], timeout=60.0
        )

        call_args = mock_handler.call_action_mock.call_args
        timeout = call_args[0][2]

        assert timeout == 60.0

    @pytest.mark.anyio
    async def test_call_tool_timeout_is_180(self):
        """call_tool timeout is 180 seconds."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"result": {}}

        ctx = create_mock_context(tools=[{"tool_name": "test_tool"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.call_tool("test_tool", {"param": "value"})

        call_args = mock_handler.call_action_mock.call_args
        timeout = call_args[0][2]

        assert timeout == 180

    @pytest.mark.anyio
    async def test_retrieve_knowledge_timeout_is_30(self):
        """retrieve_knowledge timeout is 30 seconds."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"results": []}

        ctx = create_mock_context(knowledge_bases=[{"kb_id": "kb_001"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.retrieve_knowledge("kb_001", "search query")

        call_args = mock_handler.call_action_mock.call_args
        timeout = call_args[0][2]

        assert timeout == 30

    @pytest.mark.anyio
    async def test_invoke_llm_timeout_is_bounded_by_run_deadline(self):
        """invoke_llm timeout is capped by ctx.runtime.deadline_at."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "message": {"role": "assistant", "content": "Hello"}
        }

        ctx = create_mock_context(
            deadline_at=time.time() + 5,
            models=[{"model_id": "model_001"}],
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.invoke_llm("model_001", [Message(role="user", content="Hello")])

        timeout = mock_handler.call_action_mock.call_args[0][2]
        payload_timeout = mock_handler.call_action_mock.call_args[0][1]["timeout"]

        assert 0 < timeout <= 5
        assert payload_timeout == timeout

    @pytest.mark.anyio
    async def test_call_tool_timeout_is_bounded_by_run_deadline(self):
        """tool calls use the remaining run deadline instead of the full default."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"result": {}}

        ctx = create_mock_context(
            deadline_at=time.time() + 5,
            tools=[{"tool_name": "test_tool"}],
        )
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.call_tool("test_tool", {"param": "value"})

        timeout = mock_handler.call_action_mock.call_args[0][2]

        assert 0 < timeout <= 5


class TestAgentRunAPIProxyActionEnumCorrectness:
    """Tests to ensure correct action enum usage."""

    def test_retrieve_knowledge_uses_retrieve_knowledge_base_action(self):
        """retrieve_knowledge uses RETRIEVE_KNOWLEDGE_BASE (not unrestricted RETRIEVE_KNOWLEDGE)."""
        unrestricted_action = PluginToRuntimeAction.RETRIEVE_KNOWLEDGE
        restricted_action = PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE

        assert unrestricted_action.value == "retrieve_knowledge"
        assert restricted_action.value == "retrieve_knowledge_base"
        assert unrestricted_action != restricted_action

    @pytest.mark.anyio
    async def test_retrieve_knowledge_sends_correct_action(self):
        """retrieve_knowledge sends RETRIEVE_KNOWLEDGE_BASE action."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"results": []}

        ctx = create_mock_context(knowledge_bases=[{"kb_id": "kb_001"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.retrieve_knowledge("kb_001", "search query")

        call_args = mock_handler.call_action_mock.call_args
        action = call_args[0][0]

        assert action == PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE


class TestAgentRunAPIProxyFieldConsistency:
    """Tests for field name consistency between SDK and Host handler."""

    @pytest.mark.anyio
    async def test_invoke_llm_sends_correct_fields(self):
        """INVOKE_LLM: SDK fields match Host handler expectations."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "message": {"role": "assistant", "content": "Hello"}
        }

        ctx = create_mock_context(models=[{"model_id": "model_001"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.invoke_llm("model_001", [Message(role="user", content="Hello")])

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        # Host handler expects these fields
        assert "run_id" in data
        assert "llm_model_uuid" in data
        assert "messages" in data
        assert "funcs" in data
        assert "extra_args" in data
        assert "timeout" in data

    @pytest.mark.anyio
    async def test_invoke_llm_can_send_remove_think_override(self):
        """INVOKE_LLM: remove_think override is passed when supplied."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "message": {"role": "assistant", "content": "Hello"}
        }

        ctx = create_mock_context(models=[{"model_id": "model_001"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.invoke_llm(
            "model_001", [Message(role="user", content="Hello")], remove_think=True
        )

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert data["remove_think"] is True

    @pytest.mark.anyio
    async def test_invoke_rerank_validates_authorized_model(self):
        """INVOKE_RERANK: SDK validates rerank model through ctx.resources.models."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"results": []}

        ctx = create_mock_context(models=[{"model_id": "rerank_001"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.invoke_rerank(
            "rerank_001", "query", ["doc"], extra_args={"top_n": 2}
        )

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]
        assert data["extra_args"] == {"top_n": 2}

        with pytest.raises(PermissionDeniedError):
            await proxy.invoke_rerank("rerank_999", "query", ["doc"])

    @pytest.mark.anyio
    async def test_call_tool_sends_correct_fields(self):
        """CALL_TOOL: SDK fields match Host handler expectations."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"result": {}}

        ctx = create_mock_context(tools=[{"tool_name": "test_tool"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.call_tool("test_tool", {"param": "value"})

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert "run_id" in data
        assert "tool_name" in data
        assert "parameters" in data
        assert "query_id" not in data
        assert "session" not in data

    @pytest.mark.anyio
    async def test_retrieve_knowledge_sends_correct_fields(self):
        """RETRIEVE_KNOWLEDGE_BASE: SDK fields match Host handler expectations."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"results": []}

        ctx = create_mock_context(knowledge_bases=[{"kb_id": "kb_001"}])
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.retrieve_knowledge(
            "kb_001", "search query", top_k=5, filters={"cat": "tech"}
        )

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert "run_id" in data
        assert "query_id" not in data
        assert "kb_id" in data
        assert "query_text" in data
        assert "top_k" in data
        assert "filters" in data


class TestAgentRunAPIProxyStateAPI:
    """Tests for State API proxy methods."""

    @pytest.mark.anyio
    async def test_state_get_sends_correct_fields(self):
        """STATE_GET: SDK fields match Host handler expectations."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"value": {"key": "value"}}

        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.state_get("conversation", "external.session_id")

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert "run_id" in data
        assert data["run_id"] == "test_run"
        assert "scope" in data
        assert data["scope"] == "conversation"
        assert "key" in data
        assert data["key"] == "external.session_id"

    @pytest.mark.anyio
    async def test_state_set_sends_correct_fields(self):
        """STATE_SET: SDK fields match Host handler expectations."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"success": True}

        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.state_set("conversation", "external.session_id", "sess_123")

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert "run_id" in data
        assert data["run_id"] == "test_run"
        assert "scope" in data
        assert data["scope"] == "conversation"
        assert "key" in data
        assert data["key"] == "external.session_id"
        assert "value" in data
        assert data["value"] == "sess_123"

    @pytest.mark.anyio
    async def test_state_delete_sends_correct_fields(self):
        """STATE_DELETE: SDK fields match Host handler expectations."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"success": True}

        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.state_delete("conversation", "external.session_id")

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert "run_id" in data
        assert data["run_id"] == "test_run"
        assert "scope" in data
        assert data["scope"] == "conversation"
        assert "key" in data
        assert data["key"] == "external.session_id"

    @pytest.mark.anyio
    async def test_state_list_sends_correct_fields(self):
        """STATE_LIST: SDK fields match Host handler expectations."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "keys": ["key1", "key2"],
            "has_more": False,
        }

        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        await proxy.state_list("conversation", prefix="external.", limit=50)

        call_args = mock_handler.call_action_mock.call_args
        data = call_args[0][1]

        assert "run_id" in data
        assert data["run_id"] == "test_run"
        assert "scope" in data
        assert data["scope"] == "conversation"
        assert "prefix" in data
        assert data["prefix"] == "external."
        assert "limit" in data
        assert data["limit"] == 50

    @pytest.mark.anyio
    async def test_state_get_returns_value(self):
        """STATE_GET returns value from response."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"value": {"nested": "data"}}

        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        result = await proxy.state_get("conversation", "test_key")

        assert result["value"] == {"nested": "data"}

    @pytest.mark.anyio
    async def test_state_set_returns_success(self):
        """STATE_SET returns success status."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"success": True}

        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        result = await proxy.state_set("conversation", "test_key", "test_value")

        assert result["success"] is True

    @pytest.mark.anyio
    async def test_state_list_returns_keys_and_has_more(self):
        """STATE_LIST returns keys and has_more flag."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {
            "keys": ["k1", "k2", "k3"],
            "has_more": True,
        }

        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        result = await proxy.state_list("runner", limit=100)

        assert result["keys"] == ["k1", "k2", "k3"]
        assert result["has_more"] is True

    @pytest.mark.anyio
    async def test_state_methods_use_correct_action_enum(self):
        """State methods should use correct PluginToRuntimeAction enum values."""
        mock_handler = MockHandler()
        mock_handler.call_action_mock.return_value = {"value": None}

        ctx = create_mock_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        # Test each method uses correct action
        await proxy.state_get("conversation", "key")
        call_args = mock_handler.call_action_mock.call_args
        assert call_args[0][0] == PluginToRuntimeAction.STATE_GET

        mock_handler.call_action_mock.return_value = {"success": True}
        await proxy.state_set("conversation", "key", "value")
        call_args = mock_handler.call_action_mock.call_args
        assert call_args[0][0] == PluginToRuntimeAction.STATE_SET

        await proxy.state_delete("conversation", "key")
        call_args = mock_handler.call_action_mock.call_args
        assert call_args[0][0] == PluginToRuntimeAction.STATE_DELETE

        mock_handler.call_action_mock.return_value = {"keys": [], "has_more": False}
        await proxy.state_list("conversation")
        call_args = mock_handler.call_action_mock.call_args
        assert call_args[0][0] == PluginToRuntimeAction.STATE_LIST
