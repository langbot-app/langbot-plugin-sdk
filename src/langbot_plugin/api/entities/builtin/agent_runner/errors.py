"""Agent API error model for run-scoped Host APIs."""

from __future__ import annotations

import typing

import pydantic


class AgentAPIError(pydantic.BaseModel):
    """Structured error returned or raised by AgentRunAPIProxy operations."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, typing.Any] = pydantic.Field(default_factory=dict)

    model_config = pydantic.ConfigDict(extra="forbid")


class AgentAPIException(Exception):
    """Exception wrapper carrying a stable AgentAPIError payload."""

    def __init__(self, error: AgentAPIError):
        self.error = error
        super().__init__(error.message)
