"""Agent trigger context as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic


class AgentTrigger(pydantic.BaseModel):
    """Trigger information for an agent run.

    Indicates what triggered this agent execution.
    """

    type: str
    """Trigger type, e.g., 'message.received'. Should match event.event_type or coarser."""

    source: typing.Literal[
        "platform",
        "webui",
        "api",
        "scheduler",
        "system",
        "pipeline_compat",
    ] = "pipeline_compat"
    """Source of the trigger.

    - platform: Direct platform event
    - webui: WebUI debug chat
    - api: API trigger
    - scheduler: Scheduled trigger
    - system: System event
    - pipeline_compat: Pipeline compatibility adapter
    """

    timestamp: int | None = None
    """Trigger timestamp (epoch seconds)."""
