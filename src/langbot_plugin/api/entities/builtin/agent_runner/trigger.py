"""Agent trigger context as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic


class AgentTrigger(pydantic.BaseModel):
    """Trigger information for an agent run.

    Indicates what triggered this agent execution.
    """

    type: str
    """Trigger type, e.g., 'message.received'."""

    source: typing.Literal["pipeline", "event_router"] = "pipeline"
    """Source of the trigger."""

    timestamp: int | None = None
    """Trigger timestamp (epoch seconds)."""
