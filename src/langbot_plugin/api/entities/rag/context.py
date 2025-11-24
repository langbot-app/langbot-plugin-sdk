from __future__ import annotations

import pydantic
from typing import Any


class RetrievalResultEntry(pydantic.BaseModel):
    id: str

    metadata: dict[str, Any]

    distance: float


class RetrievalContext(pydantic.BaseModel):
    """The retrieval context."""

    query: str
    """The query."""

    top_k: int
    """The top k."""

    result: list[RetrievalResultEntry]
    """The retrieval result."""