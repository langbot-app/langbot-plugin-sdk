"""Agent event, actor, subject contexts as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic


class RawEventRef(pydantic.BaseModel):
    """Reference to raw event payload stored by Host.

    Large platform payloads should be stored as artifacts and referenced here.
    """

    artifact_id: str | None = None
    """Artifact ID containing the raw payload."""

    storage_key: str | None = None
    """Storage key for raw payload (alternative to artifact)."""


class ConversationContext(pydantic.BaseModel):
    """Conversation context for an agent run.

    Carries launcher/sender/bot/pipeline/history semantics.
    """

    conversation_id: str | None = None
    """Stable conversation identifier."""

    thread_id: str | None = None
    """Thread ID within conversation (for platforms supporting threads)."""

    launcher_type: str | None = None
    """Launcher type (person, group)."""

    launcher_id: str | None = None
    """Launcher ID."""

    sender_id: str | None = None
    """Sender ID."""

    bot_id: str | None = None
    """Bot UUID."""

    workspace_id: str | None = None
    """Workspace ID (for multi-tenant scenarios)."""

    # Pipeline adapter fields
    session_id: str | None = None
    """Pipeline session identifier (prefer conversation_id for stable identity)."""

    pipeline_uuid: str | None = None
    """Pipeline UUID."""


class AgentEventContext(pydantic.BaseModel):
    """Event envelope for EBA (Event-Based Architecture) support.

    Protocol v1 is event-first: event is a required field in AgentRunContext.
    """

    event_id: str
    """Unique event identifier."""

    event_type: str
    """Event type using stable protocol names (e.g., message.received)."""

    event_time: int | None = None
    """Event timestamp (epoch seconds)."""

    source: str
    """Event source (platform, webui, api, scheduler, system, pipeline_adapter)."""

    source_event_type: str | None = None
    """Original platform event type (for debugging/logging)."""

    raw_ref: RawEventRef | None = None
    """Reference to raw event payload."""

    data: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Event payload. Large data should be in raw_ref/artifacts."""


class ActorContext(pydantic.BaseModel):
    """Actor (who triggered the event) context."""

    actor_type: str
    """Actor type (user, system, plugin)."""

    actor_id: str | None = None
    """Actor ID."""

    actor_name: str | None = None
    """Actor display name."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Additional actor metadata."""


class SubjectContext(pydantic.BaseModel):
    """Subject (what the event is about) context."""

    subject_type: str
    """Subject type (message, conversation, etc.)."""

    subject_id: str | None = None
    """Subject ID."""

    data: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Subject data."""
