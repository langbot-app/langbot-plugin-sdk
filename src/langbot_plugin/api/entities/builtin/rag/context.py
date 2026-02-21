from __future__ import annotations

import pydantic
from typing import Any
from pydantic import Field

from langbot_plugin.api.entities.builtin.provider.message import ContentElement


class RetrievalResultEntry(pydantic.BaseModel):
    """A single retrieval result entry."""

    id: str
    """Unique identifier for this result."""

    content: list[ContentElement]
    """Content elements of the result."""

    metadata: dict[str, Any]
    """Metadata associated with this result."""

    distance: float
    """Distance/dissimilarity score (lower is more similar)."""

    score: float | None = None
    """Optional similarity score (higher is more similar)."""


class RetrievalConfig(pydantic.BaseModel):
    """Configuration for retrieval operations."""

    top_k: int = Field(default=5, ge=1, le=100)
    """Number of results to retrieve."""

    similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    """Minimum similarity score threshold."""

    rerank: bool = Field(default=False)
    """Whether to apply reranking."""

    rerank_top_k: int | None = Field(default=None, ge=1)
    """Number of results after reranking."""

    custom_settings: dict[str, Any] = Field(default_factory=dict)
    """Plugin-specific retrieval settings."""


class RetrievalContext(pydantic.BaseModel):
    """The retrieval context."""

    query: str
    """The query."""

    top_k: int = pydantic.Field(default=5)
    """The top k (legacy field, kept for backward compatibility)."""

    # ========== New fields for enhanced retrieval ==========
    knowledge_base_id: str | None = None
    """Knowledge base to search in."""

    collection_id: str | None = None
    """Target vector collection ID. Defaults to knowledge_base_id if not set."""

    config: RetrievalConfig | None = None
    """New-style retrieval configuration."""

    creation_settings: dict[str, Any] = Field(default_factory=dict)
    """Creation settings of the knowledge base (e.g. API keys)."""

    filters: dict[str, Any] = Field(default_factory=dict)
    """Metadata filters for retrieval."""

    def get_top_k(self) -> int:
        """Get top_k value, supporting both old and new config styles.

        Returns:
            The top_k value from config if available, otherwise from legacy field.
        """
        return self.config.top_k if self.config else self.top_k

    def get_collection_id(self) -> str:
        """Get the collection ID, falling back to knowledge_base_id.

        Returns:
            The collection_id if set, otherwise knowledge_base_id.
        """
        return self.collection_id or self.knowledge_base_id or ""


class RetrievalResponse(pydantic.BaseModel):
    """Response from a retrieval operation."""

    results: list[RetrievalResultEntry]
    """Retrieved results."""

    total_found: int
    """Total number of results found before top_k filtering."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Additional response metadata (e.g., query rewriting info, timing)."""
