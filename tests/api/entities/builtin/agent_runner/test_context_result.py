"""Tests for AgentRunContext and AgentRunResult Protocol v1."""

from __future__ import annotations

import pytest
import pydantic

from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.result import (
    AgentRunResult,
    AgentRunResultType,
)
from langbot_plugin.api.entities.builtin.agent_runner.trigger import AgentTrigger
from langbot_plugin.api.entities.builtin.agent_runner.input import AgentInput
from langbot_plugin.api.entities.builtin.agent_runner.resources import (
    AgentResources,
    ModelResource,
    ToolResource,
    StorageResource,
)
from langbot_plugin.api.entities.builtin.agent_runner.runtime import AgentRuntimeContext
from langbot_plugin.api.entities.builtin.agent_runner.capabilities import (
    AgentRunnerCapabilities,
)
from langbot_plugin.api.entities.builtin.agent_runner.permissions import (
    AgentRunnerPermissions,
)
from langbot_plugin.api.entities.builtin.agent_runner.event import (
    ConversationContext,
    AgentEventContext,
    ActorContext,
    SubjectContext,
)
from langbot_plugin.api.entities.builtin.provider.message import (
    Message,
    MessageChunk,
    ContentElement,
)


class TestAgentRunContextV1:
    """Test AgentRunContext v1 validation."""

    def test_minimal_context_validate(self):
        """Test minimal required fields validation."""
        trigger = AgentTrigger(type="message.received", source="pipeline")
        input = AgentInput(text="Hello")
        resources = AgentResources()
        runtime = AgentRuntimeContext()

        ctx = AgentRunContext(
            run_id="run_123",
            trigger=trigger,
            input=input,
            resources=resources,
            runtime=runtime,
        )

        assert ctx.run_id == "run_123"
        assert ctx.trigger.type == "message.received"
        assert ctx.input.text == "Hello"
        assert ctx.messages == []
        assert ctx.config == {}

    def test_full_context_validate(self):
        """Test full context with all optional fields."""
        trigger = AgentTrigger(
            type="message.received", source="pipeline", timestamp=1234567890
        )
        conversation = ConversationContext(
            session_id="sess_1",
            conversation_id="conv_1",
            launcher_type="person",
            launcher_id="12345",
            sender_id="user_1",
            bot_uuid="bot_123",
            pipeline_uuid="pipe_123",
        )
        event = AgentEventContext(
            event_type="message",
            event_id="evt_1",
            event_timestamp=1234567890,
        )
        actor = ActorContext(
            actor_type="user",
            actor_id="user_1",
            actor_name="Test User",
        )
        subject = SubjectContext(
            subject_type="message",
            subject_id="msg_1",
        )
        messages = [
            Message(role="user", content="Hi"),
            Message(role="assistant", content="Hello"),
        ]
        input = AgentInput(
            text="What's up?",
            contents=[ContentElement(type="text", text="What's up?")],
        )
        resources = AgentResources(
            models=[ModelResource(model_id="gpt-4", model_type="chat")],
            tools=[ToolResource(tool_name="search", tool_type="function")],
            storage=StorageResource(plugin_storage=True, workspace_storage=True),
        )
        runtime = AgentRuntimeContext(
            langbot_version="1.0.0",
            query_id=123,
            trace_id="trace_abc",
            deadline_at=1234568000,
        )

        ctx = AgentRunContext(
            run_id="run_full",
            trigger=trigger,
            conversation=conversation,
            event=event,
            actor=actor,
            subject=subject,
            messages=messages,
            input=input,
            resources=resources,
            runtime=runtime,
            config={"model": "gpt-4"},
        )

        assert ctx.run_id == "run_full"
        assert ctx.conversation.launcher_type == "person"
        assert ctx.resources.models[0].model_id == "gpt-4"
        assert len(ctx.messages) == 2
        assert ctx.config["model"] == "gpt-4"

    def test_context_missing_required_field(self):
        """Test that missing required fields raise validation error."""
        with pytest.raises(pydantic.ValidationError):
            AgentRunContext(
                # Missing run_id, trigger, input, resources, runtime
            )

    def test_context_model_validate_from_dict(self):
        """Test model_validate from dict (as LangBot will send)."""
        data = {
            "run_id": "run_dict",
            "trigger": {"type": "message.received", "source": "pipeline"},
            "input": {"text": "Hello from dict"},
            "resources": {},
            "runtime": {"sdk_protocol_version": "1"},
        }

        ctx = AgentRunContext.model_validate(data)
        assert ctx.run_id == "run_dict"
        assert ctx.input.text == "Hello from dict"


class TestAgentRunResultV1:
    """Test AgentRunResult v1 validation for each type."""

    def test_message_delta_validate(self):
        """Test message.delta result."""
        chunk = MessageChunk(role="assistant", content="Hello")
        result = AgentRunResult.message_delta(chunk)

        assert result.type == AgentRunResultType.MESSAGE_DELTA
        assert "chunk" in result.data
        assert result.data["chunk"]["role"] == "assistant"

    def test_message_completed_validate(self):
        """Test message.completed result."""
        message = Message(role="assistant", content="Complete response")
        result = AgentRunResult.message_completed(message)

        assert result.type == AgentRunResultType.MESSAGE_COMPLETED
        assert "message" in result.data
        assert result.data["message"]["role"] == "assistant"

    def test_tool_call_started_validate(self):
        """Test tool.call.started result."""
        result = AgentRunResult.tool_call_started(
            tool_call_id="call_1",
            tool_name="weather",
            parameters={"city": "Tokyo"},
        )

        assert result.type == AgentRunResultType.TOOL_CALL_STARTED
        assert result.data["tool_call_id"] == "call_1"
        assert result.data["tool_name"] == "weather"
        assert result.data["parameters"]["city"] == "Tokyo"

    def test_tool_call_completed_validate(self):
        """Test tool.call.completed result."""
        result = AgentRunResult.tool_call_completed(
            tool_call_id="call_1",
            tool_name="weather",
            result={"temp": 25, "condition": "sunny"},
            error=None,
        )

        assert result.type == AgentRunResultType.TOOL_CALL_COMPLETED
        assert result.data["result"]["temp"] == 25

    def test_tool_call_completed_with_error(self):
        """Test tool.call.completed with error."""
        result = AgentRunResult.tool_call_completed(
            tool_call_id="call_2",
            tool_name="weather",
            result=None,
            error="API timeout",
        )

        assert result.type == AgentRunResultType.TOOL_CALL_COMPLETED
        assert result.data["error"] == "API timeout"

    def test_state_updated_validate(self):
        """Test state.updated result."""
        result = AgentRunResult.state_updated(
            key="external_conversation_id",
            value="abc123",
        )

        assert result.type == AgentRunResultType.STATE_UPDATED
        assert result.data["key"] == "external_conversation_id"
        assert result.data["value"] == "abc123"

    def test_run_completed_validate(self):
        """Test run.completed result."""
        message = Message(role="assistant", content="Done")
        result = AgentRunResult.run_completed(message=message, finish_reason="stop")

        assert result.type == AgentRunResultType.RUN_COMPLETED
        assert result.data["finish_reason"] == "stop"
        assert result.data["message"]["role"] == "assistant"

    def test_run_completed_without_message(self):
        """Test run.completed without message (when message.completed already sent)."""
        result = AgentRunResult.run_completed(finish_reason="stop")

        assert result.type == AgentRunResultType.RUN_COMPLETED
        assert result.data["finish_reason"] == "stop"
        assert "message" not in result.data

    def test_run_failed_validate(self):
        """Test run.failed result."""
        result = AgentRunResult.run_failed(
            error="Upstream timeout",
            code="upstream.timeout",
            retryable=True,
        )

        assert result.type == AgentRunResultType.RUN_FAILED
        assert result.data["error"] == "Upstream timeout"
        assert result.data["code"] == "upstream.timeout"
        assert result.data["retryable"] is True

    def test_run_failed_default_code(self):
        """Test run.failed with default code."""
        result = AgentRunResult.run_failed(error="Something went wrong")

        assert result.data["code"] == "runner.error"

    def test_action_requested_validate(self):
        """Test action.requested result."""
        result = AgentRunResult.action_requested(
            action="platform.message.edit",
            parameters={"message_id": "msg_1", "new_text": "Updated"},
        )

        assert result.type == AgentRunResultType.ACTION_REQUESTED
        assert result.data["action"] == "platform.message.edit"

    def test_result_model_dump_json(self):
        """Test model_dump(mode='json') for serialization."""
        message = Message(role="assistant", content="Test")
        result = AgentRunResult.message_completed(message)

        dumped = result.model_dump(mode="json")
        assert dumped["type"] == "message.completed"
        assert isinstance(dumped["data"]["message"]["content"], str)


class TestAgentInput:
    """Test AgentInput helpers."""

    def test_to_text_from_text_field(self):
        """Test to_text when text field is set."""
        input = AgentInput(text="Hello world")
        assert input.to_text() == "Hello world"

    def test_to_text_from_contents(self):
        """Test to_text from content elements."""
        input = AgentInput(
            contents=[
                ContentElement(type="text", text="Hello"),
                ContentElement(type="text", text="world"),
            ]
        )
        assert input.to_text() == "Hello world"

    def test_to_text_empty(self):
        """Test to_text with no text."""
        input = AgentInput(
            contents=[
                ContentElement(
                    type="image_url", image_url={"url": "http://example.com"}
                )
            ]
        )
        assert input.to_text() == ""


class TestCapabilitiesAndPermissions:
    """Test AgentRunnerCapabilities and AgentRunnerPermissions."""

    def test_capabilities_defaults(self):
        """Test all capabilities default to False."""
        caps = AgentRunnerCapabilities()
        assert not caps.streaming
        assert not caps.tool_calling
        assert not caps.knowledge_retrieval
        assert not caps.multimodal_input
        assert not caps.event_context
        assert not caps.platform_api
        assert not caps.interrupt
        assert not caps.stateful_session

    def test_permissions_defaults(self):
        """Test all permissions default to empty lists."""
        perms = AgentRunnerPermissions()
        assert perms.models == []
        assert perms.tools == []
        assert perms.knowledge_bases == []
        assert perms.storage == []
        assert perms.files == []
        assert perms.platform_api == []

    def test_capabilities_from_dict(self):
        """Test capabilities from manifest data."""
        caps = AgentRunnerCapabilities(
            streaming=True,
            tool_calling=True,
            stateful_session=True,
        )
        assert caps.streaming
        assert caps.tool_calling
        assert caps.stateful_session

    def test_permissions_from_dict(self):
        """Test permissions from manifest data."""
        perms = AgentRunnerPermissions(
            models=["list", "invoke", "stream"],
            tools=["list", "detail", "call"],
            storage=["plugin", "workspace"],
        )
        assert perms.models == ["list", "invoke", "stream"]
        assert perms.tools == ["list", "detail", "call"]
        assert perms.storage == ["plugin", "workspace"]
