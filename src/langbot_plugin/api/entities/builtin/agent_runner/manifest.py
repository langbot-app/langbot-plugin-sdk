"""AgentRunner manifest as defined in Protocol v1.

The manifest describes an AgentRunner component's metadata,
capabilities, permissions, and context policy.
"""

from __future__ import annotations

import typing
import pydantic

from langbot_plugin.api.entities.builtin.agent_runner.capabilities import (
    AgentRunnerCapabilities,
)
from langbot_plugin.api.entities.builtin.agent_runner.permissions import (
    AgentRunnerPermissions,
)
from langbot_plugin.api.entities.builtin.agent_runner.context_policy import (
    AgentRunnerContextPolicy,
)


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


class AgentRunnerManifest(pydantic.BaseModel):
    """Manifest describing an AgentRunner component.

    This is the stable descriptor returned during LIST_AGENT_RUNNERS.
    Contains metadata, capabilities, permissions, and config schema.
    """

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
    """Runner permissions."""

    context: AgentRunnerContextPolicy = pydantic.Field(
        default_factory=AgentRunnerContextPolicy
    )
    """Context policy."""

    config_schema: list[DynamicFormItemSchema] = pydantic.Field(default_factory=list)
    """Configuration form schema for binding config."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Additional metadata for display, diagnostics, non-stable extensions."""
