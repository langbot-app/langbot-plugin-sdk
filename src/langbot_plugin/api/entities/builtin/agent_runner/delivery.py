"""DeliveryContext as defined in Protocol v1.

Delivery context describes the output surface and platform capabilities.
"""

from __future__ import annotations

import typing
import pydantic


class DeliveryContext(pydantic.BaseModel):
    """Delivery context for the agent run.

    Tells the runner what output capabilities are available,
    such as streaming, editing, reactions, and platform-specific features.
    """

    surface: str
    """Output surface type (platform, webui, api, etc.)."""

    reply_target: dict[str, typing.Any] | None = None
    """Target for reply (message_id, conversation_id, etc.)."""

    supports_streaming: bool = False
    """Whether streaming output is supported."""

    supports_edit: bool = False
    """Whether message editing is supported."""

    supports_reaction: bool = False
    """Whether message reactions are supported."""

    max_message_size: int | None = None
    """Maximum message size in characters/bytes."""

    platform_capabilities: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Platform-specific capabilities."""
