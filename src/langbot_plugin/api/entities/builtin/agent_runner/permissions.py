"""AgentRunner permissions as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic


class AgentRunnerPermissions(pydantic.BaseModel):
    """Permissions requested by an AgentRunner component.

    All fields default to empty list. These represent the upper limit
    of what a runner can request. LangBot execution must further filter
    based on Pipeline/Bot binding scope and user configuration to
    produce ctx.resources.
    """

    models: list[typing.Literal["list", "invoke", "stream", "embedding"]] = (
        pydantic.Field(default_factory=list)
    )
    """Model operations allowed."""

    tools: list[typing.Literal["list", "detail", "call"]] = pydantic.Field(
        default_factory=list
    )
    """Tool operations allowed."""

    knowledge_bases: list[typing.Literal["list", "retrieve"]] = pydantic.Field(
        default_factory=list
    )
    """Knowledge base operations allowed."""

    storage: list[typing.Literal["plugin", "workspace"]] = pydantic.Field(
        default_factory=list
    )
    """Storage scopes allowed."""

    files: list[typing.Literal["config", "knowledge"]] = pydantic.Field(
        default_factory=list
    )
    """File access scopes allowed."""

    platform_api: list[str] = pydantic.Field(default_factory=list)
    """Platform API actions allowed (future feature)."""
