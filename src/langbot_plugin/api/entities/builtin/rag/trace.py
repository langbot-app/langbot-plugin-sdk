"""Trace context models shared by LangBot and KnowledgeEngine plugins."""

from __future__ import annotations

from typing import Any

import pydantic
from pydantic import Field


class TraceContext(pydantic.BaseModel):
    """Host trace context propagated to plugin RAG operations."""

    trace_id: str
    """Identifier for the end-to-end LangBot request trace."""

    parent_span_id: str | None = None
    """Span that plugin-generated spans should attach to."""

    message_id: str | None = None
    """Monitoring message identifier associated with the user request."""

    query_id: int | None = None
    """LangBot in-process query identifier, if available."""

    session_id: str | None = None
    """Monitoring session identifier."""

    bot_id: str | None = None
    """Bot UUID associated with the request."""

    pipeline_id: str | None = None
    """Pipeline UUID associated with the request."""

    knowledge_base_id: str | None = None
    """Knowledge base identifier associated with the RAG operation."""

    attributes: dict[str, Any] = Field(default_factory=dict)
    """Additional privacy-conscious host attributes."""
