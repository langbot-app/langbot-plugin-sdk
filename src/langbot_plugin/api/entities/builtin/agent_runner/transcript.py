"""Transcript item entity for history projection."""
from __future__ import annotations

import typing
import pydantic


class TranscriptItem(pydantic.BaseModel):
    """A single item in the transcript history projection.

    Transcript is the conversation-oriented view of events, designed for
    agent history retrieval and UI display. It does not include raw platform
    payloads or large artifacts.
    """

    transcript_id: str
    """Unique transcript item identifier."""

    event_id: str
    """Reference to the source event in EventLog."""

    conversation_id: str | None = None
    """Conversation this item belongs to."""

    thread_id: str | None = None
    """Thread ID if platform supports threads."""

    role: str
    """Message role: 'user', 'assistant', 'system', or 'tool'."""

    item_type: str = "message"
    """Item type: 'message', 'tool_call', 'tool_result', 'system'."""

    content: str | None = None
    """Text content summary (may be truncated for large messages)."""

    content_json: dict[str, typing.Any] | None = None
    """Full structured content if available (Message model dump)."""

    artifact_refs: list[dict[str, typing.Any]] = pydantic.Field(default_factory=list)
    """References to artifacts (images, files) attached to this item."""

    seq: int | None = None
    """Sequence number within conversation (for cursor-based pagination)."""

    cursor: str | None = None
    """Cursor string for pagination (derived from seq)."""

    created_at: int | None = None
    """Unix timestamp when the item was created."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Additional metadata (sender_id, platform, etc.)."""

    model_config = pydantic.ConfigDict(extra='forbid')
