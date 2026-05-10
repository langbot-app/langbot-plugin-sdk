"""Agent input entity as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic

from langbot_plugin.api.entities.builtin.provider.message import ContentElement


class AgentInput(pydantic.BaseModel):
    """Input for an agent run.

    Contains the user's input in multiple formats for convenience.
    """

    text: str | None = None
    """Plain text input."""

    contents: list[ContentElement] = pydantic.Field(default_factory=list)
    """Structured content elements (text, images, files, etc.)."""

    message_chain: list[dict[str, typing.Any]] | dict[str, typing.Any] | None = None
    """Raw platform message chain (list of message components or dict representation)."""

    attachments: list[dict[str, typing.Any]] = pydantic.Field(default_factory=list)
    """File attachments metadata."""

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
