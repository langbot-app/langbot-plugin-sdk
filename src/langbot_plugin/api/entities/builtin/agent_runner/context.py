"""Agent run context as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic

from langbot_plugin.api.entities.builtin.provider.message import Message
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
    - params: single-run public business parameters (read-only, non-persistent)
    - resources: authorized resources
    - state: host-managed scoped state snapshot (durable)
    - runtime: host/environment info
    - config: runner instance configuration

    Field boundaries:
    - config: Static runner configuration from pipeline/runner config.
    - params: Single-run business parameters, read-only, non-persistent.
    - state: Host-managed runner-scoped persistent state snapshot.
    - runtime.metadata: Host/runtime observability info, not a business input contract.
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

    params: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Single-run public business parameters.

    Semantics:
    - JSON-safe, read-only for runner
    - Non-persistent (not carried to next run)
    - Not equivalent to LangBot query.variables
    - Host should filter internal variables, secrets, permission control variables

    Use cases:
    - Workflow inputs
    - Prompt variables
    - Pipeline pre-stage generated public business variables
    - User-defined variables
    """

    resources: AgentResources
    """Authorized resources."""

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
    """Runner instance configuration."""

    class Config:
        arbitrary_types_allowed = True