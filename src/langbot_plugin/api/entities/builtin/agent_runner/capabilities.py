"""AgentRunner capabilities as defined in Protocol v1."""

from __future__ import annotations

import pydantic


class AgentRunnerCapabilities(pydantic.BaseModel):
    """Capabilities declared by an AgentRunner component.

    All fields default to False. LangBot uses these to determine
    what features the runner may use during execution.
    """

    streaming: bool = False
    """Runner may output message.delta events."""

    tool_calling: bool = False
    """Runner needs tool list/detail/call operations."""

    knowledge_retrieval: bool = False
    """Runner needs knowledge base list or retrieval."""

    multimodal_input: bool = False
    """Runner can process image/file/audio non-text input."""

    event_context: bool = False
    """Runner will read ctx.event/actor/subject."""

    platform_api: bool = False
    """Runner may request platform actions (future feature, not executed this phase)."""

    interrupt: bool = False
    """Runner supports cancel or interrupt operations."""

    stateful_session: bool = False
    """Runner maintains external conversation/session state."""
