"""Agent event, actor, subject contexts as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic


class ConversationContext(pydantic.BaseModel):
    """Conversation context for an agent run.

    Carries launcher/sender/bot/pipeline/history semantics.
    """

    session_id: str | None = None
    """Session identifier."""

    conversation_id: str | None = None
    """Conversation identifier."""

    launcher_type: str | None = None
    """Launcher type (person, group)."""

    launcher_id: str | None = None
    """Launcher ID."""

    sender_id: str | None = None
    """Sender ID."""

    bot_uuid: str | None = None
    """Bot UUID."""

    pipeline_uuid: str | None = None
    """Pipeline UUID."""


class AgentEventContext(pydantic.BaseModel):
    """Event envelope subset for EBA (Event-Based Architecture) support."""

    event_type: str | None = None
    """Event type."""

    event_id: str | None = None
    """Event ID."""

    event_timestamp: int | None = None
    """Event timestamp."""

    event_data: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Event payload."""


class ActorContext(pydantic.BaseModel):
    """Actor (who triggered the event) context."""

    actor_type: str | None = None
    """Actor type (user, system, plugin)."""

    actor_id: str | None = None
    """Actor ID."""

    actor_name: str | None = None
    """Actor display name."""


class SubjectContext(pydantic.BaseModel):
    """Subject (what the event is about) context."""

    subject_type: str | None = None
    """Subject type (message, conversation, etc.)."""

    subject_id: str | None = None
    """Subject ID."""

    subject_data: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Subject data."""
