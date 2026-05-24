"""BootstrapContext as defined in Protocol v1.

Bootstrap context is optional convenience provided by Host.
It is NOT the full history - it's a small bootstrap window.
"""

from __future__ import annotations

import typing
import pydantic

from langbot_plugin.api.entities.builtin.provider.message import Message
from langbot_plugin.api.entities.builtin.agent_runner.input import ArtifactRef


class BootstrapContext(pydantic.BaseModel):
    """Bootstrap context optionally provided by Host.

    Constraints:
    - bootstrap.messages is Host convenience, NOT protocol core.
    - Self-managed context runners should receive empty bootstrap or only current event.
    - Host MUST NOT inline full transcript just to "help" the agent.
    - Pipeline adapter max-round only affects adapter bootstrap, NOT Protocol v1 fields.
    """

    messages: list[Message] = pydantic.Field(default_factory=list)
    """Bootstrap messages (small window, not full history)."""

    summary: str | None = None
    """Optional summary of earlier context."""

    artifacts: list[ArtifactRef] = pydantic.Field(default_factory=list)
    """Artifact references in bootstrap."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Additional bootstrap metadata."""
