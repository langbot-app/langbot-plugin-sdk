"""Runtime registry entities for AgentRunner control-plane APIs."""

from __future__ import annotations

import typing

import pydantic


class AgentRuntime(pydantic.BaseModel):
    """Host-owned runtime registry record."""

    runtime_id: str
    status: str
    display_name: str | None = None
    endpoint: str | None = None
    version: str | None = None
    capabilities: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    labels: dict[str, str] = pydantic.Field(default_factory=dict)
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    last_heartbeat_at: int | None = None
    heartbeat_deadline_at: int | None = None
    created_at: int | None = None
    updated_at: int | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class RuntimePage(pydantic.BaseModel):
    """Paged result for runtime.list APIs."""

    items: list[AgentRuntime] = pydantic.Field(default_factory=list)
    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
    total_count: int = 0

    model_config = pydantic.ConfigDict(extra="forbid")
