"""RAG-related entities and protocols."""

from __future__ import annotations

# Enumerations
from .enums import (
    DocumentStatus,
    ChunkingStrategy,
    IndexingMode,
)

# Data models
from .models import (
    FileMetadata,
    FileObject,
    TextChunk,
    IngestionContext,
    IngestionResult,
    FileStreamHandle,
)

# Error types
from .errors import (
    RAGError,
    HostServiceError,
    EmbeddingError,
    VectorStoreError,
    CollectionNotFoundError,
    FileServiceError,
    IngestionError,
    RetrievalError,
    ParsingError,
    ChunkingError,
)

# Host services protocols
from .host_services import (
    EmbedderProtocol,
    VectorStoreProtocol,
    HostServices,
)

# Context and retrieval types
from .context import (
    RetrievalResultEntry,
    RetrievalConfig,
    RetrievalContext,
    RetrievalResponse,
)

__all__ = [
    # Enums
    "DocumentStatus",
    "ChunkingStrategy",
    "IndexingMode",
    # Models
    "FileMetadata",
    "FileObject",
    "TextChunk",
    "IngestionContext",
    "IngestionResult",
    "FileStreamHandle",
    # Errors
    "RAGError",
    "HostServiceError",
    "EmbeddingError",
    "VectorStoreError",
    "CollectionNotFoundError",
    "FileServiceError",
    "IngestionError",
    "RetrievalError",
    "ParsingError",
    "ChunkingError",
    # Host services
    "EmbedderProtocol",
    "VectorStoreProtocol",
    "HostServices",
    # Context
    "RetrievalResultEntry",
    "RetrievalConfig",
    "RetrievalContext",
    "RetrievalResponse",
]
