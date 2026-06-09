"""Artifact entities for Host-owned artifact store."""

from __future__ import annotations

import typing
import pydantic


class ArtifactMetadata(pydantic.BaseModel):
    """Metadata for an artifact in the Host store.

    Artifacts are large files, images, tool results, or platform attachments
    that should not be inlined into AgentRunContext. They are stored by Host
    and accessed via pull APIs by authorized runners.
    """

    artifact_id: str
    """Unique artifact identifier."""

    artifact_type: str
    """Artifact type: 'image', 'file', 'voice', 'tool_result', 'platform_attachment', etc."""

    mime_type: str | None = None
    """MIME type of the content."""

    name: str | None = None
    """Original file name (if applicable)."""

    size_bytes: int | None = None
    """Size in bytes."""

    sha256: str | None = None
    """SHA256 hash of content (for integrity verification)."""

    source: str
    """Source of artifact: 'platform', 'runner', 'tool', 'system'."""

    conversation_id: str | None = None
    """Conversation this artifact belongs to."""

    run_id: str | None = None
    """Run ID that created this artifact."""

    runner_id: str | None = None
    """Runner ID that created this artifact."""

    created_at: int | None = None
    """Unix timestamp when artifact was created."""

    expires_at: int | None = None
    """Unix timestamp when artifact expires (optional)."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Additional metadata (platform-specific info, etc.)."""

    model_config = pydantic.ConfigDict(extra="forbid")


class ArtifactReadResult(pydantic.BaseModel):
    """Result of reading artifact content.

    Supports two modes:
    1. Inline bytes (small artifacts): returns content_base64
    2. File key reference (large artifacts): returns file_key for chunked transfer

    Host may enforce max read size limits to prevent memory exhaustion.
    """

    artifact_id: str
    """Artifact identifier."""

    mime_type: str | None = None
    """MIME type of the content."""

    size_bytes: int | None = None
    """Total size of artifact in bytes."""

    offset: int = 0
    """Offset of this read (for range reads)."""

    length: int | None = None
    """Length of data read (None if using file_key)."""

    content_base64: str | None = None
    """Base64-encoded content (for small artifacts or range reads)."""

    file_key: str | None = None
    """File key for chunked transfer (for large artifacts)."""

    has_more: bool = False
    """Whether more data is available (for range reads)."""

    model_config = pydantic.ConfigDict(extra="forbid")
