"""AgentRunner manifest as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic


# I18n object: maps locale code to localized string
I18nObject = dict[str, str]


class DynamicFormItemSchema(pydantic.BaseModel):
    """Schema for a dynamic form configuration item.

    Represents a form field in the runner's config schema.
    """

    type: str
    """Field type (text, select, llm-model-selector, etc.)."""

    name: str
    """Field name/key."""

    label: I18nObject = pydantic.Field(default_factory=dict)
    """Localized label."""

    description: I18nObject | None = None
    """Localized description."""

    required: bool = False
    """Whether the field is required."""

    default: typing.Any = None
    """Default value."""

    options: list[dict[str, typing.Any]] | None = None
    """Options for select/radio types."""

    # Allow additional properties for form item flexibility
    model_config = pydantic.ConfigDict(extra="allow")


class AgentRunnerCapabilities(pydantic.BaseModel):
    """Capabilities declared by an AgentRunner component."""

    streaming: bool = False
    """Runner may output message.delta events."""

    tool_calling: bool = False
    """Runner needs host tool detail/call operations."""

    knowledge_retrieval: bool = False
    """Runner needs host knowledge base retrieval operations."""

    multimodal_input: bool = False
    """Runner can process non-text input contents or attachments."""

    skill_authoring: bool = False
    """Runner wants Host-provided skill authoring tools when available."""

    interrupt: bool = False
    """Runner supports cancel or interrupt operations."""

    steering: bool = False
    """Runner can pull run-scoped steering/follow-up input at turn boundaries."""

    model_config = pydantic.ConfigDict(extra="forbid")


class AgentRunnerPermissions(pydantic.BaseModel):
    """LangBot resource permissions requested by an AgentRunner component.

    These declarations are only an upper bound for LangBot-managed resources.
    The Host must intersect them with the binding policy for the current run.
    They do not constrain native capabilities of an external harness.
    """

    models: list[typing.Literal["invoke", "stream", "rerank"]] = pydantic.Field(
        default_factory=list
    )
    """Model operations allowed."""

    tools: list[typing.Literal["detail", "call"]] = pydantic.Field(default_factory=list)
    """Tool operations allowed."""

    knowledge_bases: list[typing.Literal["list", "retrieve"]] = pydantic.Field(
        default_factory=list
    )
    """Knowledge base operations allowed."""

    history: list[typing.Literal["page", "search"]] = pydantic.Field(
        default_factory=list
    )
    """History operations allowed."""

    events: list[typing.Literal["get", "page"]] = pydantic.Field(default_factory=list)
    """Event operations allowed."""

    storage: list[typing.Literal["plugin", "workspace"]] = pydantic.Field(
        default_factory=list
    )
    """Storage scopes allowed."""

    model_config = pydantic.ConfigDict(extra="forbid")


class AgentRunnerManifest(pydantic.BaseModel):
    """Stable AgentRunner descriptor returned during LIST_AGENT_RUNNERS."""

    id: str
    """Unique runner ID. Recommended format: plugin:author/plugin_name/runner_name."""

    name: str
    """Runner name within the plugin (e.g., 'default')."""

    label: I18nObject
    """Localized display name."""

    description: I18nObject | None = None
    """Localized description."""

    capabilities: AgentRunnerCapabilities = pydantic.Field(
        default_factory=AgentRunnerCapabilities
    )
    """Runner capabilities."""

    permissions: AgentRunnerPermissions = pydantic.Field(
        default_factory=AgentRunnerPermissions
    )
    """Requested LangBot resource permissions."""

    config_schema: list[DynamicFormItemSchema] = pydantic.Field(default_factory=list)
    """Configuration form schema for Agent/runner config."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Additional metadata for display, diagnostics, non-stable extensions."""

    model_config = pydantic.ConfigDict(extra="forbid")
