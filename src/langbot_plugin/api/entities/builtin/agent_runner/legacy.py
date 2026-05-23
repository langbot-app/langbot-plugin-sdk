"""Legacy helpers for migrating from PoC AgentRunReturn to Protocol v1.

These helpers are ONLY for official plugin migration.
They should NOT be used as target models for LangBot context construction.

DEPRECATED: Do not use AgentRunReturn in new plugins.
"""

from __future__ import annotations

import typing
import pydantic
import warnings

from langbot_plugin.api.entities.builtin.provider.message import (
    Message,
    MessageChunk,
    ContentElement,
    ToolCall,
)
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.result import AgentRunResult
from langbot_plugin.api.entities.builtin.agent_runner.input import AgentInput
from langbot_plugin.api.entities.builtin.agent_runner.event import ConversationContext
from langbot_plugin.api.entities.builtin.agent_runner.trigger import AgentTrigger


class AgentRunReturn(pydantic.BaseModel):
    """DEPRECATED: Legacy return value from PoC AgentRunner.

    Use AgentRunResult instead.

    Migration guide:
    - type='chunk', message_chunk -> AgentRunResult.message_delta(chunk)
    - type='text', content -> AgentRunResult.message_completed(Message with content)
    - type='tool_call', tool_calls -> AgentRunResult.tool_call_started/completed
    - type='finish', message, finish_reason -> AgentRunResult.run_completed()
    - type='finish', finish_reason='error', content -> AgentRunResult.run_failed()
    """

    type: str
    """Return type: 'text' | 'chunk' | 'tool_call' | 'finish' - DEPRECATED."""

    content: str | None = None
    """Text content for 'text' and 'chunk' types - DEPRECATED."""

    message: Message | None = None
    """Complete message for 'finish' type - DEPRECATED."""

    message_chunk: MessageChunk | None = None
    """Message chunk for 'chunk' type - DEPRECATED."""

    tool_calls: list[ToolCall] | None = None
    """Tool calls for 'tool_call' type - DEPRECATED."""

    finish_reason: str | None = None
    """Finish reason for 'finish' type - DEPRECATED."""

    class Config:
        arbitrary_types_allowed = True

    def to_v1_result(self, run_id: str = "legacy") -> AgentRunResult:
        """Convert legacy AgentRunReturn to v1 AgentRunResult.

        WARNING: This is a migration helper only.

        Args:
            run_id: Run identifier (defaults to "legacy" for backward compatibility).
                Callers should pass the actual run_id from context if available.
        """
        warnings.warn(
            "AgentRunReturn is deprecated. Use AgentRunResult instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        if self.type == "chunk":
            if self.message_chunk:
                return AgentRunResult.message_delta(run_id, self.message_chunk)
            elif self.content:
                # Create a simple chunk from content
                chunk = MessageChunk(role="assistant", content=self.content)
                return AgentRunResult.message_delta(run_id, chunk)
            else:
                return AgentRunResult.run_failed(
                    run_id, "Empty chunk content", "conversion.error"
                )

        elif self.type == "text":
            if self.content:
                message = Message(role="assistant", content=self.content)
                return AgentRunResult.message_completed(run_id, message)
            else:
                return AgentRunResult.run_failed(
                    run_id, "Empty text content", "conversion.error"
                )

        elif self.type == "tool_call":
            if self.tool_calls:
                # Only report first tool call for legacy conversion
                tc = self.tool_calls[0]
                return AgentRunResult.tool_call_started(
                    run_id=run_id,
                    tool_call_id=tc.id,
                    tool_name=tc.function.name,
                    parameters={"arguments": tc.function.arguments},
                )
            else:
                return AgentRunResult.run_failed(run_id, "Empty tool_calls", "conversion.error")

        elif self.type == "finish":
            if self.finish_reason == "error":
                return AgentRunResult.run_failed(
                    run_id=run_id,
                    error=self.content or "Unknown error",
                    code="runner.error",
                )
            else:
                return AgentRunResult.run_completed(
                    run_id=run_id,
                    message=self.message,
                    finish_reason=self.finish_reason or "stop",
                )

        else:
            return AgentRunResult.run_failed(
                run_id=run_id,
                error=f"Unknown legacy type: {self.type}",
                code="conversion.error",
            )


def create_legacy_context(
    query_id: int,
    session: typing.Any,
    messages: list[Message],
    user_message: ContentElement,
    use_funcs: list[typing.Any],
    extra_config: dict[str, typing.Any],
) -> AgentRunContext:
    """Create v1 AgentRunContext from legacy PoC parameters.

    DEPRECATED: LangBot should directly construct AgentRunContext v1.

    Args:
        query_id: Legacy query ID
        session: Legacy Session object with launcher_type, launcher_id, sender_id
        messages: Historical messages
        user_message: Current user message as ContentElement
        use_funcs: Available tools (LLMTool list)
        extra_config: Extra configuration from pipeline

    Returns:
        AgentRunContext v1
    """
    warnings.warn(
        "create_legacy_context is deprecated. LangBot should construct AgentRunContext directly.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Extract conversation info from session
    launcher_type = None
    launcher_id = None
    sender_id = None
    if hasattr(session, "launcher_type"):
        launcher_type = (
            session.launcher_type.value
            if hasattr(session.launcher_type, "value")
            else str(session.launcher_type)
        )
    if hasattr(session, "launcher_id"):
        launcher_id = str(session.launcher_id)
    if hasattr(session, "sender_id"):
        sender_id = str(session.sender_id) if session.sender_id else None

    conversation = ConversationContext(
        session_id=None,
        conversation_id=None,
        launcher_type=launcher_type,
        launcher_id=launcher_id,
        sender_id=sender_id,
        bot_uuid=None,
        pipeline_uuid=None,
    )

    # Build input
    input_text = None
    input_contents: list[ContentElement] = []
    if user_message:
        if user_message.type == "text" and user_message.text:
            input_text = user_message.text
        input_contents = [user_message]

    agent_input = AgentInput(
        text=input_text,
        contents=input_contents,
        message_chain=None,
        attachments=[],
    )

    # Build resources (legacy only has tools)
    from langbot_plugin.api.entities.builtin.agent_runner.resources import (
        AgentResources,
        ToolResource,
        StorageResource,
    )

    tool_resources: list[ToolResource] = []
    for func in use_funcs:
        if hasattr(func, "function"):
            tool_resources.append(
                ToolResource(
                    tool_name=func.function.name
                    if hasattr(func.function, "name")
                    else str(func),
                    tool_type=None,
                    description=None,
                )
            )
        else:
            tool_resources.append(
                ToolResource(
                    tool_name=str(func),
                    tool_type=None,
                    description=None,
                )
            )

    resources = AgentResources(
        models=[],
        tools=tool_resources,
        knowledge_bases=[],
        files=[],
        storage=StorageResource(),
        platform_capabilities={},
    )

    trigger = AgentTrigger(
        type="message.received",
        source="pipeline",
        timestamp=None,
    )

    from langbot_plugin.api.entities.builtin.agent_runner.runtime import (
        AgentRuntimeContext,
    )
    from langbot_plugin.api.entities.builtin.agent_runner.event import AgentEventContext
    from langbot_plugin.api.entities.builtin.agent_runner.delivery import DeliveryContext
    from langbot_plugin.api.entities.builtin.agent_runner.bootstrap import BootstrapContext
    from langbot_plugin.api.entities.builtin.agent_runner.context_access import ContextAccess

    runtime = AgentRuntimeContext(
        langbot_version=None,
        sdk_protocol_version="1",
        query_id=query_id,
        trace_id=None,
        deadline_at=None,
        metadata={},
    )

    # Build event context (REQUIRED for Protocol v1)
    event = AgentEventContext(
        event_id=str(query_id),
        event_type="message.received",
        event_time=None,
        source="pipeline",
        source_event_type=None,
        data={},
    )

    # Build delivery context (REQUIRED for Protocol v1)
    delivery = DeliveryContext(
        surface="pipeline",
        reply_target=None,
        supports_streaming=False,
        supports_edit=False,
        supports_reaction=False,
        max_message_size=None,
        platform_capabilities={},
    )

    # Build bootstrap context with historical messages
    bootstrap = BootstrapContext(
        messages=messages,
        summary=None,
        artifacts=[],
        metadata={},
    )

    return AgentRunContext(
        run_id=f"run_{query_id}",
        trigger=trigger,
        conversation=conversation,
        event=event,  # REQUIRED
        actor=None,
        subject=None,
        input=agent_input,
        delivery=delivery,  # REQUIRED
        resources=resources,
        context=ContextAccess(),  # REQUIRED
        state={},
        runtime=runtime,
        config=extra_config,
        bootstrap=bootstrap,  # Historical messages go here
        compatibility=None,
        metadata={},
    )
