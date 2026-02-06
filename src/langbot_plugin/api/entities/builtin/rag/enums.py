"""RAG-related enumerations."""

from __future__ import annotations

import enum


class DocumentStatus(str, enum.Enum):
    """Document processing status."""

    PENDING = "pending"
    """Document is queued for processing."""

    PROCESSING = "processing"
    """Document is being processed."""

    COMPLETED = "completed"
    """Document has been successfully processed."""

    FAILED = "failed"
    """Document processing failed."""

    DELETED = "deleted"
    """Document has been deleted."""


class ChunkingStrategy(str, enum.Enum):
    """Text chunking strategies."""

    FIXED_SIZE = "fixed_size"
    """Fixed-size chunking with configurable overlap."""

    SEMANTIC = "semantic"
    """Semantic chunking based on content structure."""

    SLIDING_WINDOW = "sliding_window"
    """Sliding window with configurable size and stride."""

    PARAGRAPH = "paragraph"
    """Split by paragraphs."""

    SENTENCE = "sentence"
    """Split by sentences."""


class IndexingMode(str, enum.Enum):
    """Knowledge base indexing modes."""

    GENERAL = "general"
    """General-purpose indexing for diverse content."""

    QA = "qa"
    """Question-Answer pair extraction and indexing."""

    PARENT_CHILD = "parent_child"
    """Parent-child chunking for hierarchical retrieval."""

    HYBRID = "hybrid"
    """Hybrid indexing combining multiple strategies."""
