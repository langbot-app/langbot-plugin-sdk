"""Agent resources entity as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic


class ModelResource(pydantic.BaseModel):
    """Model resource available to the agent."""

    model_id: str
    """Model identifier."""

    model_type: str | None = None
    """Model type (chat, embedding, etc.)."""

    provider: str | None = None
    """Model provider name."""

    operations: list[typing.Literal["invoke", "stream", "rerank"]] = pydantic.Field(
        default_factory=list
    )
    """Model operations authorized for this run."""


class ToolResource(pydantic.BaseModel):
    """Tool resource available to the agent."""

    tool_name: str
    """Tool name."""

    tool_type: str | None = None
    """Tool type."""

    description: str | None = None
    """Tool description."""

    operations: list[typing.Literal["detail", "call"]] = pydantic.Field(
        default_factory=list
    )
    """Tool operations authorized for this run."""


class KnowledgeBaseResource(pydantic.BaseModel):
    """Knowledge base resource available to the agent."""

    kb_id: str
    """Knowledge base identifier."""

    kb_name: str | None = None
    """Knowledge base display name."""

    kb_type: str | None = None
    """Knowledge base type."""

    operations: list[typing.Literal["list", "retrieve"]] = pydantic.Field(
        default_factory=list
    )
    """Knowledge-base operations authorized for this run."""


class SkillResource(pydantic.BaseModel):
    """Skill resource available to the agent."""

    skill_name: str
    """Skill name used by the activate tool."""

    display_name: str | None = None
    """Skill display name."""

    description: str | None = None
    """Skill description."""


class StorageResource(pydantic.BaseModel):
    """Storage resources available to the agent."""

    plugin_storage: bool = False
    """Whether plugin storage is accessible."""

    workspace_storage: bool = False
    """Whether workspace storage is accessible."""


class AgentResources(pydantic.BaseModel):
    """Resources available to an agent run.

    Represents what LangBot has authorized for this run.
    LangBot host must still validate actual calls.
    """

    models: list[ModelResource] = pydantic.Field(default_factory=list)
    """Available models."""

    tools: list[ToolResource] = pydantic.Field(default_factory=list)
    """Available tools."""

    knowledge_bases: list[KnowledgeBaseResource] = pydantic.Field(default_factory=list)
    """Available knowledge bases."""

    skills: list[SkillResource] = pydantic.Field(default_factory=list)
    """Available skills."""

    storage: StorageResource = pydantic.Field(default_factory=StorageResource)
    """Storage access."""

    platform_capabilities: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Platform capabilities available."""
