"""Agent input entity as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic

from langbot_plugin.api.entities.builtin.provider.message import ContentElement


class ArtifactRef(pydantic.BaseModel):
    """Reference to an artifact (file, image, tool result, etc.).

    Large content should be stored as artifacts and referenced here.
    """

    artifact_id: str
    """Artifact identifier."""

    artifact_type: str | None = None
    """Artifact type (image, file, voice, tool_result, etc.)."""

    mime_type: str | None = None
    """MIME type."""

    size: int | None = None
    """Size in bytes."""

    name: str | None = None
    """File name (if applicable)."""

    source: str | None = None
    """Attachment source, such as url, base64, or platform message-chain."""

    url: str | None = None
    """External URL when the artifact is backed by a URL."""

    content: str | None = None
    """Base64 or data URL content for small current-event attachments."""

    id: str | None = None
    """Platform-native attachment identifier when available."""


class AgentInput(pydantic.BaseModel):
    """Input for an agent run.

    Contains the user's input in multiple formats for convenience.
    Protocol v1: input is required; attachments use ArtifactRef.
    """

    text: str | None = None
    """Plain text input."""

    contents: list[ContentElement] = pydantic.Field(default_factory=list)
    """Structured content elements (text, images, files, etc.)."""

    message_chain: list[dict[str, typing.Any]] | dict[str, typing.Any] | None = None
    """Raw platform message chain reference (adapter field, not stable dependency)."""

    attachments: list[ArtifactRef] = pydantic.Field(default_factory=list)
    """Artifact references for files/images/attachments."""

    def to_text(self) -> str:
        """Extract plain text from input.

        Returns text if available, otherwise concatenates text content elements.
        """
        if self.text is not None:
            return self.text

        text_parts = []
        for content in self.contents:
            if content.type == "text" and content.text:
                text_parts.append(content.text)

        return " ".join(text_parts)
