from __future__ import annotations

import pydantic
from typing import Any

from langbot_plugin.api.entities.builtin.provider.message import ContentElement


class RetrievalResultEntry(pydantic.BaseModel):
    id: str

    content: list[ContentElement]

    metadata: dict[str, Any]

    distance: float


class RetrievalContext(pydantic.BaseModel):
    """The retrieval context."""

    query: str
    """The query."""

    top_k: int = pydantic.Field(default=5)
    """The top k."""
