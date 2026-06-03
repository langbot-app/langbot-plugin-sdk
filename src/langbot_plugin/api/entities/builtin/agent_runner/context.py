"""Agent run context as defined in Protocol v1."""

from __future__ import annotations

import typing

import pydantic
from langbot_plugin.api.entities.builtin.agent_runner.trigger import AgentTrigger
from langbot_plugin.api.entities.builtin.agent_runner.input import AgentInput
from langbot_plugin.api.entities.builtin.agent_runner.resources import AgentResources
from langbot_plugin.api.entities.builtin.agent_runner.runtime import AgentRuntimeContext
from langbot_plugin.api.entities.builtin.agent_runner.state import AgentRunState
from langbot_plugin.api.entities.builtin.agent_runner.event import (
    ConversationContext,
    AgentEventContext,
    ActorContext,
    SubjectContext,
)
from langbot_plugin.api.entities.builtin.agent_runner.context_access import ContextAccess
from langbot_plugin.api.entities.builtin.agent_runner.delivery import DeliveryContext


class AdapterContext(pydantic.BaseModel):
    """Context for host entry-adapter metadata.

    This context holds adapter-specific fields that are not part of the stable
    event/input/resource contract.
    """

    extra: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Other adapter-specific fields."""


class AgentRunContext(pydantic.BaseModel):
    """Agent run context passed to AgentRunner.run().

    Protocol v1 context structure. This is event-first:
    - event is REQUIRED (not optional)
    - input is REQUIRED (current event input, not history)
    - messages is not part of the context; runners pull history through APIs
    - adapter holds non-core Host entry-adapter metadata

    Field boundaries:
    - config: Current agent/runner configuration from Host.
    - adapter.extra: Adapter-specific fields such as entry params.
    - state: Host-managed runner-scoped persistent state snapshot.
    - runtime.metadata: Host/runtime observability info, not a business input contract.
    """

    run_id: str
    """Unique identifier for this run."""

    trigger: AgentTrigger
    """Trigger information."""

    event: AgentEventContext
    """Event context (REQUIRED for Protocol v1)."""

    conversation: ConversationContext | None = None
    """Conversation context."""

    actor: ActorContext | None = None
    """Actor context."""

    subject: SubjectContext | None = None
    """Subject context."""

    input: AgentInput
    """User input (current event input, not history)."""

    delivery: DeliveryContext
    """Delivery context (output surface capabilities)."""

    resources: AgentResources
    """Authorized resources."""

    context: ContextAccess = pydantic.Field(default_factory=ContextAccess)
    """Context access descriptor (what's inlined, what APIs are available)."""

    state: AgentRunState = pydantic.Field(default_factory=AgentRunState)
    """Host-managed scoped state snapshot.

    Semantics:
    - Scoped (conversation/actor/subject/runner)
    - Durable (host persists and reloads next run)
    - Runner can read and request updates via state.updated result

    Scopes:
    - conversation: Current conversation + current runner state
    - actor: Current user long-term state or preferences
    - subject: Current group/channel/object state
    - runner: Runner instance-level state (use sparingly)
    """

    runtime: AgentRuntimeContext
    """Runtime context."""

    config: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Current agent/runner configuration from Host."""

    adapter: AdapterContext | None = None
    """Adapter context for host entry-adapter metadata.

    Runners should prefer stable protocol fields and pull APIs when possible.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Additional metadata."""

    class Config:
        arbitrary_types_allowed = True
