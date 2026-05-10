"""Agent run context as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic

from langbot_plugin.api.entities.builtin.provider.message import Message
from langbot_plugin.api.entities.builtin.agent_runner.trigger import AgentTrigger
from langbot_plugin.api.entities.builtin.agent_runner.input import AgentInput
from langbot_plugin.api.entities.builtin.agent_runner.resources import AgentResources
from langbot_plugin.api.entities.builtin.agent_runner.runtime import AgentRuntimeContext
from langbot_plugin.api.entities.builtin.agent_runner.event import (
    ConversationContext,
    AgentEventContext,
    ActorContext,
    SubjectContext,
)


class AgentRunContext(pydantic.BaseModel):
    """Agent run context passed to AgentRunner.run().

    Protocol v1 context structure. Contains:
    - run_id: unique identifier for this run
    - trigger: what triggered this run
    - conversation: launcher/sender/bot/pipeline info
    - event: event envelope subset (for future EBA)
    - actor: who triggered the event
    - subject: what the event is about
    - messages: historical conversation messages
    - input: user input
    - resources: authorized resources
    - runtime: host/environment info
    - config: runner instance configuration
    """

    run_id: str
    """Unique identifier for this run."""

    trigger: AgentTrigger
    """Trigger information."""

    conversation: ConversationContext | None = None
    """Conversation context."""

    event: AgentEventContext | None = None
    """Event context (for EBA)."""

    actor: ActorContext | None = None
    """Actor context."""

    subject: SubjectContext | None = None
    """Subject context."""

    messages: list[Message] = pydantic.Field(default_factory=list)
    """Historical messages in the conversation."""

    input: AgentInput
    """User input."""

    resources: AgentResources
    """Authorized resources."""

    runtime: AgentRuntimeContext
    """Runtime context."""

    config: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Runner instance configuration."""

    class Config:
        arbitrary_types_allowed = True
