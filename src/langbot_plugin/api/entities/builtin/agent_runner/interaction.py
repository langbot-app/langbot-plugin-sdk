"""Structured interaction entities for AgentRunner Protocol v1."""

from __future__ import annotations

import typing

import pydantic


INTERACTION_REQUESTED_ACTION = "interaction.requested"
INTERACTION_SUBMITTED_EVENT = "interaction.submitted"

InteractionFieldType = typing.Literal[
    "text",
    "textarea",
    "select",
    "multiselect",
    "number",
    "boolean",
    "file",
]
InteractionActionStyle = typing.Literal["default", "primary", "danger"]
JSONValue = pydantic.JsonValue


class InteractionOption(pydantic.BaseModel):
    """One selectable value in an interaction field."""

    value: str = pydantic.Field(min_length=1, max_length=512)
    label: str = pydantic.Field(min_length=1, max_length=512)
    description: str | None = pydantic.Field(default=None, max_length=2000)

    model_config = pydantic.ConfigDict(extra="forbid")


class InteractionField(pydantic.BaseModel):
    """A Host-renderable field in an interaction request."""

    id: str = pydantic.Field(min_length=1, max_length=128)
    label: str = pydantic.Field(min_length=1, max_length=512)
    type: InteractionFieldType
    required: bool = False
    options: list[InteractionOption] = pydantic.Field(default_factory=list, max_length=100)
    placeholder: str | None = pydantic.Field(default=None, max_length=1000)
    default: JSONValue = None

    model_config = pydantic.ConfigDict(extra="forbid")


class InteractionAction(pydantic.BaseModel):
    """A submit action rendered by the Host."""

    id: str = pydantic.Field(min_length=1, max_length=128)
    label: str = pydantic.Field(min_length=1, max_length=512)
    style: InteractionActionStyle = "default"

    model_config = pydantic.ConfigDict(extra="forbid")


class InteractionRequest(pydantic.BaseModel):
    """A runner request for Host-owned structured user interaction."""

    interaction_id: str = pydantic.Field(min_length=1, max_length=255)
    kind: typing.Literal["form", "confirmation", "choice"] = "form"
    title: str = pydantic.Field(min_length=1, max_length=1000)
    description: str | None = pydantic.Field(default=None, max_length=10000)
    fields: list[InteractionField] = pydantic.Field(default_factory=list, max_length=50)
    actions: list[InteractionAction] = pydantic.Field(default_factory=list, max_length=20)
    expires_at: int | None = None
    fallback_text: str = pydantic.Field(min_length=1, max_length=20000)

    model_config = pydantic.ConfigDict(extra="forbid")


class InteractionSubmission(pydantic.BaseModel):
    """Host-validated user input for a previous interaction request."""

    interaction_id: str = pydantic.Field(min_length=1, max_length=255)
    action_id: str | None = pydantic.Field(default=None, max_length=128)
    values: dict[str, JSONValue] = pydantic.Field(default_factory=dict)
    submitted_at: int | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class InteractionDeliveryCapabilities(pydantic.BaseModel):
    """Structured interaction features supported by a delivery surface."""

    field_types: list[InteractionFieldType] = pydantic.Field(default_factory=list)
    action_styles: list[InteractionActionStyle] = pydantic.Field(default_factory=list)
    supports_updates: bool = False
    max_fields: int | None = pydantic.Field(default=None, ge=0)

    model_config = pydantic.ConfigDict(extra="forbid")


__all__ = [
    "INTERACTION_REQUESTED_ACTION",
    "INTERACTION_SUBMITTED_EVENT",
    "InteractionAction",
    "InteractionActionStyle",
    "InteractionDeliveryCapabilities",
    "InteractionField",
    "InteractionFieldType",
    "InteractionOption",
    "InteractionRequest",
    "InteractionSubmission",
    "JSONValue",
]
