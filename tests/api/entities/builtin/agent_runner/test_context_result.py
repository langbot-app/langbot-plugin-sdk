"""Tests for AgentRunContext and AgentRunResult Protocol v1."""

from __future__ import annotations

import pytest
import pydantic

from langbot_plugin.api.entities.builtin.agent_runner.context import (
    AgentRunContext,
    AdapterContext,
)
from langbot_plugin.api.entities.builtin.agent_runner.result import (
    AgentRunResult,
    AgentRunResultType,
    ARTIFACT_CREATED_CONTENT_BASE64_MAX_BYTES,
)
from langbot_plugin.api.entities.builtin.agent_runner.errors import AgentAPIError
from langbot_plugin.api.entities.builtin.agent_runner.steering import SteeringPullResult
from langbot_plugin.api.entities.builtin.agent_runner.trigger import AgentTrigger
from langbot_plugin.api.entities.builtin.agent_runner.input import AgentInput
from langbot_plugin.api.entities.builtin.agent_runner.resources import (
    AgentResources,
    ModelResource,
    ToolResource,
    SkillResource,
    StorageResource,
)
from langbot_plugin.api.entities.builtin.agent_runner.runtime import AgentRuntimeContext
from langbot_plugin.api.entities.builtin.agent_runner.state import (
    AgentRunState,
    VALID_STATE_SCOPES,
)
from langbot_plugin.api.entities.builtin.agent_runner.event import (
    ConversationContext,
    AgentEventContext,
    ActorContext,
    SubjectContext,
)
from langbot_plugin.api.entities.builtin.agent_runner.context_access import (
    ContextAccess,
)
from langbot_plugin.api.entities.builtin.agent_runner.delivery import DeliveryContext
from langbot_plugin.api.entities.builtin.agent_runner.manifest import (
    AgentRunnerCapabilities,
    AgentRunnerManifest,
    AgentRunnerPermissions,
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
        trigger = AgentTrigger(type="message.received", source="host_adapter")
        event = AgentEventContext(
            event_id="evt_1",
            event_type="message.received",
            source="platform",
        )
        input = AgentInput(text="Hello")
        resources = AgentResources()
        runtime = AgentRuntimeContext()
        delivery = DeliveryContext(surface="platform")

        ctx = AgentRunContext(
            run_id="run_123",
            trigger=trigger,
            event=event,
            input=input,
            delivery=delivery,
            resources=resources,
            runtime=runtime,
        )

        assert ctx.run_id == "run_123"
        assert ctx.trigger.type == "message.received"
        assert ctx.input.text == "Hello"
        assert ctx.config == {}
        assert ctx.context is not None  # Has default
        assert ctx.context.available_apis.prompt_get is False
        assert "protocol_version" not in ctx.runtime.model_dump()
        assert "sdk_protocol_version" not in AgentRuntimeContext.model_fields

    def test_event_is_required(self):
        """Test that event is required for Protocol v1."""
        trigger = AgentTrigger(type="message.received")
        input = AgentInput(text="Hello")
        resources = AgentResources()
        runtime = AgentRuntimeContext()
        delivery = DeliveryContext(surface="platform")

        # Missing event should raise validation error
        with pytest.raises(pydantic.ValidationError):
            AgentRunContext(
                run_id="run_123",
                trigger=trigger,
                # event missing - should fail
                input=input,
                delivery=delivery,
                resources=resources,
                runtime=runtime,
            )

    def test_history_messages_are_not_context_fields(self):
        """History messages are pulled through APIs, not embedded in context."""
        trigger = AgentTrigger(type="message.received")
        event = AgentEventContext(
            event_id="evt_1",
            event_type="message.received",
            source="platform",
        )
        input = AgentInput(text="Hello")
        resources = AgentResources()
        runtime = AgentRuntimeContext()
        delivery = DeliveryContext(surface="platform")

        ctx = AgentRunContext(
            run_id="run_123",
            trigger=trigger,
            event=event,
            input=input,
            delivery=delivery,
            resources=resources,
            runtime=runtime,
        )

        assert "messages" not in AgentRunContext.model_fields
        assert "bootstrap" not in AgentRunContext.model_fields
        assert not hasattr(ctx, "bootstrap")

    def test_context_access_default(self):
        """Test ContextAccess default values."""
        context_access = ContextAccess()

        assert context_access.conversation_id is None
        assert context_access.has_history_before is False
        assert context_access.inline_policy.mode == "current_event"

    def test_adapter_context(self):
        """Test AdapterContext for non-core entry adapter fields."""
        adapter = AdapterContext(
            extra={"entrypoint": "host_adapter"},
        )

        assert adapter.extra["entrypoint"] == "host_adapter"
        assert set(AdapterContext.model_fields) == {"extra"}

    def test_full_context_validate(self):
        """Test full context with all optional fields."""
        trigger = AgentTrigger(
            type="message.received", source="host_adapter", timestamp=1234567890
        )
        conversation = ConversationContext(
            conversation_id="conv_1",
            thread_id="thread_1",
            launcher_type="person",
            launcher_id="12345",
            sender_id="user_1",
            bot_id="bot_123",
            workspace_id="ws_1",
        )
        event = AgentEventContext(
            event_id="evt_1",
            event_type="message.received",
            event_time=1234567890,
            source="platform",
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
        input = AgentInput(
            text="What's up?",
            contents=[ContentElement(type="text", text="What's up?")],
        )
        resources = AgentResources(
            models=[ModelResource(model_id="gpt-4", model_type="chat")],
            tools=[ToolResource(tool_name="search", tool_type="function")],
            skills=[SkillResource(skill_name="pdf", display_name="PDF", description="Work with PDFs")],
            storage=StorageResource(plugin_storage=True, workspace_storage=True),
        )
        state = AgentRunState(
            conversation={"external.conversation_id": "conv_xyz"},
            actor={"memory.summary": "User likes coffee"},
        )
        runtime = AgentRuntimeContext(
            langbot_version="1.0.0",
            trace_id="trace_abc",
            deadline_at=1234568000,
        )
        delivery = DeliveryContext(
            surface="platform",
            supports_streaming=True,
        )
        context_access = ContextAccess(
            conversation_id="conv_1",
            has_history_before=True,
        )

        ctx = AgentRunContext(
            run_id="run_full",
            trigger=trigger,
            conversation=conversation,
            event=event,
            actor=actor,
            subject=subject,
            input=input,
            delivery=delivery,
            resources=resources,
            context=context_access,
            state=state,
            runtime=runtime,
            config={"model": "gpt-4"},
        )

        assert ctx.run_id == "run_full"
        assert ctx.conversation.launcher_type == "person"
        assert ctx.resources.models[0].model_id == "gpt-4"
        assert ctx.resources.skills[0].skill_name == "pdf"
        assert ctx.config["model"] == "gpt-4"
        assert ctx.context.has_history_before is True

    def test_context_missing_required_field(self):
        """Test that missing required fields raise validation error."""
        with pytest.raises(pydantic.ValidationError):
            AgentRunContext(
                # Missing run_id, trigger, event, input, delivery, resources, runtime
            )

    def test_context_model_validate_from_dict(self):
        """Test model_validate from dict (as LangBot will send)."""
        data = {
            "run_id": "run_dict",
            "trigger": {"type": "message.received", "source": "host_adapter"},
            "event": {
                "event_id": "evt_1",
                "event_type": "message.received",
                "source": "platform",
            },
            "input": {"text": "Hello from dict"},
            "delivery": {"surface": "platform"},
            "resources": {},
            "runtime": {},
        }

        ctx = AgentRunContext.model_validate(data)
        assert ctx.run_id == "run_dict"
        assert ctx.input.text == "Hello from dict"
        assert ctx.event.event_type == "message.received"


class TestAgentRunState:
    """Test AgentRunState entity."""

    def test_state_default_factory(self):
        """Test state creates with all empty dicts."""
        state = AgentRunState()
        assert state.conversation == {}
        assert state.actor == {}
        assert state.subject == {}
        assert state.runner == {}

    def test_state_with_values(self):
        """Test state with actual values."""
        state = AgentRunState(
            conversation={
                "external.conversation_id": "abc",
                "external.thread_id": "xyz",
            },
            actor={"preferred_language": "zh"},
            subject={"group_topic": "general"},
            runner={"cache_version": 1},
        )

        assert state.conversation["external.conversation_id"] == "abc"
        assert state.actor["preferred_language"] == "zh"
        assert state.subject["group_topic"] == "general"
        assert state.runner["cache_version"] == 1

    def test_state_model_dump(self):
        """Test state serialization."""
        state = AgentRunState(
            conversation={"key": "value"},
        )
        dumped = state.model_dump()
        assert dumped["conversation"]["key"] == "value"
        assert dumped["actor"] == {}

    def test_valid_state_scopes_constant(self):
        """Test VALID_STATE_SCOPES contains all scopes."""
        assert "conversation" in VALID_STATE_SCOPES
        assert "actor" in VALID_STATE_SCOPES
        assert "subject" in VALID_STATE_SCOPES
        assert "runner" in VALID_STATE_SCOPES
        assert len(VALID_STATE_SCOPES) == 4


class TestAgentRunResultV1:
    """Test AgentRunResult v1 validation for each type."""

    def test_message_delta_validate(self):
        """Test message.delta result."""
        chunk = MessageChunk(role="assistant", content="Hello")
        result = AgentRunResult.message_delta("run_1", chunk)

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.MESSAGE_DELTA
        assert "chunk" in result.data
        assert result.data["chunk"]["role"] == "assistant"

    def test_message_completed_validate(self):
        """Test message.completed result."""
        message = Message(role="assistant", content="Complete response")
        result = AgentRunResult.message_completed("run_1", message)

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.MESSAGE_COMPLETED
        assert "message" in result.data
        assert result.data["message"]["role"] == "assistant"

    def test_artifact_created_validate(self):
        """Test artifact.created result."""
        result = AgentRunResult.artifact_created(
            run_id="run_1",
            artifact_id="artifact_1",
            artifact_type="image",
            mime_type="image/png",
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.ARTIFACT_CREATED
        assert result.data["artifact_id"] == "artifact_1"

    def test_artifact_created_allows_host_generated_id(self):
        """artifact.created may omit artifact_id so Host can generate one."""
        result = AgentRunResult.artifact_created(
            run_id="run_1",
            artifact_type="file",
            mime_type="text/plain",
        )

        assert result.type == AgentRunResultType.ARTIFACT_CREATED
        assert result.data["artifact_type"] == "file"
        assert "artifact_id" not in result.data

    def test_artifact_created_with_new_fields(self):
        """Test artifact.created with all new fields."""
        import base64

        content = b"test image content"
        result = AgentRunResult.artifact_created(
            run_id="run_1",
            artifact_id="artifact_1",
            artifact_type="image",
            mime_type="image/png",
            name="test.png",
            size_bytes=len(content),
            sha256="abc123",
            metadata={"source": "generated"},
            content_base64=base64.b64encode(content).decode("utf-8"),
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.ARTIFACT_CREATED
        assert result.data["artifact_id"] == "artifact_1"
        assert result.data["artifact_type"] == "image"
        assert result.data["mime_type"] == "image/png"
        assert result.data["name"] == "test.png"
        assert result.data["size_bytes"] == len(content)
        assert result.data["sha256"] == "abc123"
        assert result.data["metadata"] == {"source": "generated"}
        assert result.data["content_base64"] == base64.b64encode(content).decode(
            "utf-8"
        )

    def test_artifact_created_metadata_only(self):
        """Test artifact.created without content (metadata-only)."""
        result = AgentRunResult.artifact_created(
            run_id="run_1",
            artifact_id="artifact_1",
            artifact_type="file",
            mime_type="application/pdf",
            name="document.pdf",
            size_bytes=1024,
            sha256="abc123",
            metadata={"source": "external"},
        )

        assert result.data["artifact_id"] == "artifact_1"
        # content_base64 is not added when not provided
        assert "content_base64" not in result.data

    def test_artifact_created_rejects_invalid_content_base64(self):
        """Test artifact.created validates inline content."""
        with pytest.raises(pydantic.ValidationError, match="valid base64"):
            AgentRunResult.artifact_created(
                run_id="run_1",
                artifact_id="artifact_1",
                artifact_type="file",
                content_base64="not base64",
            )

    def test_artifact_created_rejects_oversized_inline_content(self):
        """Test artifact.created enforces inline content size."""
        import base64

        oversized = b"x" * (ARTIFACT_CREATED_CONTENT_BASE64_MAX_BYTES + 1)
        with pytest.raises(pydantic.ValidationError, match="exceeds"):
            AgentRunResult.artifact_created(
                run_id="run_1",
                artifact_id="artifact_1",
                artifact_type="file",
                content_base64=base64.b64encode(oversized).decode("utf-8"),
            )

    def test_tool_call_started_validate(self):
        """Test tool.call.started result."""
        result = AgentRunResult.tool_call_started(
            run_id="run_1",
            tool_call_id="call_1",
            tool_name="weather",
            parameters={"city": "Tokyo"},
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.TOOL_CALL_STARTED
        assert result.data["tool_call_id"] == "call_1"
        assert result.data["tool_name"] == "weather"
        assert result.data["parameters"]["city"] == "Tokyo"

    def test_tool_call_completed_validate(self):
        """Test tool.call.completed result."""
        result = AgentRunResult.tool_call_completed(
            run_id="run_1",
            tool_call_id="call_1",
            tool_name="weather",
            result={"temp": 25, "condition": "sunny"},
            error=None,
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.TOOL_CALL_COMPLETED
        assert result.data["result"]["temp"] == 25

    def test_tool_call_completed_with_error(self):
        """Test tool.call.completed with error."""
        result = AgentRunResult.tool_call_completed(
            run_id="run_1",
            tool_call_id="call_2",
            tool_name="weather",
            result=None,
            error="API timeout",
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.TOOL_CALL_COMPLETED
        assert result.data["error"] == "API timeout"

    def test_state_updated_validate(self):
        """Test state.updated result."""
        result = AgentRunResult.state_updated(
            run_id="run_1",
            key="external.conversation_id",
            value="abc123",
            scope="conversation",
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.STATE_UPDATED
        assert result.data["scope"] == "conversation"
        assert result.data["key"] == "external.conversation_id"
        assert result.data["value"] == "abc123"

    def test_state_updated_with_scope(self):
        """Test state.updated with explicit scope."""
        result = AgentRunResult.state_updated(
            run_id="run_1",
            key="preferred_language",
            value="en",
            scope="actor",
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.STATE_UPDATED
        assert result.data["scope"] == "actor"
        assert result.data["key"] == "preferred_language"
        assert result.data["value"] == "en"

    def test_state_updated_all_scopes(self):
        """Test state.updated with all valid scopes."""
        for scope in VALID_STATE_SCOPES:
            result = AgentRunResult.state_updated(
                run_id="run_1",
                key="test_key",
                value="test_value",
                scope=scope,
            )
            assert result.data["scope"] == scope

    def test_state_updated_invalid_scope_raises(self):
        """Test state.updated with invalid scope raises ValueError."""
        with pytest.raises(ValueError, match="Invalid scope"):
            AgentRunResult.state_updated(
                run_id="run_1",
                key="test_key",
                value="test_value",
                scope="invalid_scope",
            )

    def test_run_completed_validate(self):
        """Test run.completed result."""
        message = Message(role="assistant", content="Done")
        result = AgentRunResult.run_completed(
            run_id="run_1", message=message, finish_reason="stop"
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.RUN_COMPLETED
        assert result.data["finish_reason"] == "stop"
        assert result.data["message"]["role"] == "assistant"

    def test_run_completed_without_message(self):
        """Test run.completed without message (when message.completed already sent)."""
        result = AgentRunResult.run_completed(run_id="run_1", finish_reason="stop")

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.RUN_COMPLETED
        assert result.data["finish_reason"] == "stop"
        assert "message" not in result.data

    def test_run_failed_validate(self):
        """Test run.failed result."""
        result = AgentRunResult.run_failed(
            run_id="run_1",
            error="Upstream timeout",
            code="upstream.timeout",
            retryable=True,
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.RUN_FAILED
        assert result.data["error"] == "Upstream timeout"
        assert result.data["code"] == "upstream.timeout"
        assert result.data["retryable"] is True

    def test_run_failed_default_code(self):
        """Test run.failed with default code."""
        result = AgentRunResult.run_failed(run_id="run_1", error="Something went wrong")

        assert result.data["code"] == "runner.error"

    def test_action_requested_validate(self):
        """Test action.requested result."""
        result = AgentRunResult.action_requested(
            run_id="run_1",
            action="platform.message.edit",
            target={"message_id": "msg_1"},
            payload={"new_text": "Updated"},
        )

        assert result.run_id == "run_1"
        assert result.type == AgentRunResultType.ACTION_REQUESTED
        assert result.data["action"] == "platform.message.edit"

    def test_result_model_dump_json(self):
        """Test model_dump(mode='json') for serialization."""
        message = Message(role="assistant", content="Test")
        result = AgentRunResult.message_completed("run_1", message)

        dumped = result.model_dump(mode="json")
        assert dumped["type"] == "message.completed"
        assert isinstance(dumped["data"]["message"]["content"], str)

    def test_unknown_result_type_is_accepted_for_forward_compatibility(self):
        """SDK model accepts unknown result type strings for Protocol v1 evolution."""
        result = AgentRunResult.model_validate(
            {
                "run_id": "run_1",
                "type": "future.result",
                "data": {"value": 1},
                "sequence": 7,
            }
        )

        assert result.type == "future.result"
        assert result.sequence == 7

    def test_sequence_can_be_set_by_factories(self):
        """Factories accept sequence for runtime-managed streams."""
        message = Message(role="assistant", content="Done")
        result = AgentRunResult.message_completed("run_1", message, sequence=3)

        assert result.sequence == 3


class TestAgentRunAPIContractEntities:
    """Test SDK entities that back AgentRunAPIProxy contract."""

    def test_agent_api_error_validate(self):
        error = AgentAPIError(
            code="history.unauthorized",
            message="not allowed",
            retryable=False,
            details={"scope": "conversation"},
        )

        assert error.code == "history.unauthorized"
        assert error.details["scope"] == "conversation"

    def test_steering_pull_result_validate(self):
        result = SteeringPullResult.model_validate(
            {
                "items": [
                    {
                        "claimed_run_id": "run_1",
                        "runner_id": "plugin:test/demo/default",
                        "event": {
                            "event_id": "evt_1",
                            "event_type": "message.received",
                            "source": "platform",
                        },
                        "input": {"text": "follow up"},
                    }
                ]
            }
        )

        assert result.items[0].input.text == "follow up"


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


class TestAgentRunnerManifest:
    """Test AgentRunnerManifest."""

    def test_manifest_minimal(self):
        """Test minimal manifest."""
        manifest = AgentRunnerManifest(
            id="plugin:author/plugin/runner",
            name="default",
            label={"en_US": "Default Runner"},
        )

        assert manifest.id == "plugin:author/plugin/runner"
        assert manifest.name == "default"
        assert isinstance(manifest.capabilities, AgentRunnerCapabilities)
        assert isinstance(manifest.permissions, AgentRunnerPermissions)
        assert manifest.capabilities.streaming is False
        assert manifest.permissions.models == []

    def test_manifest_full(self):
        """Test full manifest."""
        manifest = AgentRunnerManifest(
            id="plugin:author/plugin/runner",
            name="default",
            label={"en_US": "Runner"},
            description={"en_US": "A runner"},
            capabilities={"streaming": True, "tool_calling": True},
            permissions={
                "models": ["invoke", "stream"],
                "tools": ["detail", "call"],
                "history": ["page"],
            },
        )

        assert manifest.description == {"en_US": "A runner"}
        assert manifest.capabilities.streaming is True
        assert manifest.permissions.models == ["invoke", "stream"]
        assert manifest.permissions.history == ["page"]

    def test_manifest_rejects_unknown_capability_key(self):
        """Test non-standard capability keys are rejected."""
        with pytest.raises(pydantic.ValidationError, match="extra_forbidden"):
            AgentRunnerManifest(
                id="plugin:author/plugin/runner",
                name="default",
                label={"en_US": "Runner"},
                capabilities={"event_context": True},
            )

    def test_manifest_rejects_platform_api_permission(self):
        """Test platform_api is not a Protocol v1 permission."""
        with pytest.raises(pydantic.ValidationError, match="extra_forbidden"):
            AgentRunnerManifest(
                id="plugin:author/plugin/runner",
                name="default",
                label={"en_US": "Runner"},
                permissions={"platform_api": ["message.send"]},
            )


class TestEventContextProtocolV1:
    """Test event context for Protocol v1."""

    def test_event_context_required_fields(self):
        """Test event context required fields."""
        event = AgentEventContext(
            event_id="evt_1",
            event_type="message.received",
            source="platform",
        )

        assert event.event_id == "evt_1"
        assert event.event_type == "message.received"
        assert event.source == "platform"

    def test_event_context_missing_required(self):
        """Test event context with missing required fields."""
        with pytest.raises(pydantic.ValidationError):
            AgentEventContext(
                # Missing event_id, event_type, source
            )


class TestDeliveryContext:
    """Test DeliveryContext."""

    def test_delivery_context_required(self):
        """Test delivery context required field."""
        delivery = DeliveryContext(surface="platform")

        assert delivery.surface == "platform"
        assert delivery.supports_streaming is False
        assert delivery.reply_target is None

    def test_delivery_context_full(self):
        """Test full delivery context."""
        delivery = DeliveryContext(
            surface="webui",
            supports_streaming=True,
            supports_edit=True,
            max_message_size=4096,
        )

        assert delivery.surface == "webui"
        assert delivery.supports_streaming is True
        assert delivery.max_message_size == 4096
