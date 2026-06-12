"""AgentRunResult as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic
import enum
import base64
import binascii

from langbot_plugin.api.entities.builtin.provider.message import Message, MessageChunk
from langbot_plugin.api.entities.builtin.agent_runner.state import (
    VALID_STATE_SCOPES,
    STATE_SCOPE_LITERAL,
)

ARTIFACT_CREATED_CONTENT_BASE64_MAX_BYTES = 1024 * 1024


class AgentRunResultType(str, enum.Enum):
    """Type of AgentRunResult event."""

    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    STATE_UPDATED = "state.updated"
    ARTIFACT_CREATED = "artifact.created"
    ACTION_REQUESTED = "action.requested"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class MessageDeltaPayload(pydantic.BaseModel):
    """Payload for message.delta."""

    chunk: MessageChunk

    model_config = pydantic.ConfigDict(extra="forbid")


class MessageCompletedPayload(pydantic.BaseModel):
    """Payload for message.completed."""

    message: Message

    model_config = pydantic.ConfigDict(extra="forbid")


class ToolCallStartedPayload(pydantic.BaseModel):
    """Payload for tool.call.started."""

    tool_call_id: str
    tool_name: str
    parameters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)

    model_config = pydantic.ConfigDict(extra="forbid")


class ToolCallCompletedPayload(pydantic.BaseModel):
    """Payload for tool.call.completed."""

    tool_call_id: str
    tool_name: str
    result: dict[str, typing.Any] | None = None
    error: str | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class ArtifactCreatedPayload(pydantic.BaseModel):
    """Payload for artifact.created."""

    artifact_id: str | None = None
    artifact_type: str
    mime_type: str | None = None
    name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    metadata: dict[str, typing.Any] | None = None
    content_base64: str | None = None

    @pydantic.field_validator("content_base64")
    @classmethod
    def validate_content_base64_size(cls, value: str | None) -> str | None:
        if value is None:
            return None

        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("content_base64 must be valid base64") from exc

        if len(decoded) > ARTIFACT_CREATED_CONTENT_BASE64_MAX_BYTES:
            raise ValueError(
                "content_base64 decoded content exceeds "
                f"{ARTIFACT_CREATED_CONTENT_BASE64_MAX_BYTES} bytes"
            )

        return value

    model_config = pydantic.ConfigDict(extra="forbid")


class StateUpdatedPayload(pydantic.BaseModel):
    """Payload for state.updated."""

    scope: STATE_SCOPE_LITERAL
    key: str
    value: typing.Any

    model_config = pydantic.ConfigDict(extra="forbid")


class RunCompletedPayload(pydantic.BaseModel):
    """Payload for run.completed."""

    finish_reason: str = "stop"
    message: Message | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class RunFailedPayload(pydantic.BaseModel):
    """Payload for run.failed."""

    error: str
    code: str = "runner.error"
    retryable: bool = False

    model_config = pydantic.ConfigDict(extra="forbid")


class ActionRequestedPayload(pydantic.BaseModel):
    """Payload for action.requested."""

    action: str
    target: dict[str, typing.Any] | None = None
    payload: dict[str, typing.Any] | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class AgentRunResult(pydantic.BaseModel):
    """Result event from AgentRunner.run().

    Protocol v1 result structure:
    - run_id: Links result to the run
    - type: Result type
    - data: Type-specific payload
    - sequence: Optional sequence number for ordering
    - timestamp: Optional timestamp

    Each yield from the runner's run() method produces one AgentRunResult.
    LangBot maps these to appropriate host delivery events.
    """

    run_id: str
    """Run identifier linking this result to the run."""

    type: AgentRunResultType | str
    """Result type. Unknown strings are accepted for forward compatibility."""

    data: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Result data."""

    sequence: int | None = None
    """Optional sequence number for ordering."""

    timestamp: int | None = None
    """Optional timestamp (epoch seconds)."""

    @classmethod
    def message_delta(
        cls,
        run_id: str,
        chunk: MessageChunk,
        *,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create a message.delta result.

        LangBot maps this to MessageChunk for streaming output.
        """
        payload = MessageDeltaPayload(chunk=chunk)
        return cls(
            run_id=run_id,
            type=AgentRunResultType.MESSAGE_DELTA,
            data=payload.model_dump(mode="json"),
            sequence=sequence,
            timestamp=timestamp,
        )

    @classmethod
    def message_completed(
        cls,
        run_id: str,
        message: Message,
        *,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create a message.completed result.

        LangBot maps this to a complete Message.
        """
        payload = MessageCompletedPayload(message=message)
        return cls(
            run_id=run_id,
            type=AgentRunResultType.MESSAGE_COMPLETED,
            data=payload.model_dump(mode="json"),
            sequence=sequence,
            timestamp=timestamp,
        )

    @classmethod
    def tool_call_started(
        cls,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        parameters: dict[str, typing.Any],
        *,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create a tool.call.started result.

        LangBot records this for telemetry/debug.
        """
        payload = ToolCallStartedPayload(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            parameters=parameters,
        )
        return cls(
            run_id=run_id,
            type=AgentRunResultType.TOOL_CALL_STARTED,
            data=payload.model_dump(mode="json"),
            sequence=sequence,
            timestamp=timestamp,
        )

    @classmethod
    def tool_call_completed(
        cls,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        result: dict[str, typing.Any] | None = None,
        error: str | None = None,
        *,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create a tool.call.completed result.

        LangBot records this for telemetry/debug.
        """
        payload = ToolCallCompletedPayload(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            result=result,
            error=error,
        )
        return cls(
            run_id=run_id,
            type=AgentRunResultType.TOOL_CALL_COMPLETED,
            data=payload.model_dump(mode="json"),
            sequence=sequence,
            timestamp=timestamp,
        )

    @classmethod
    def artifact_created(
        cls,
        run_id: str,
        artifact_id: str | None = None,
        artifact_type: str | None = None,
        mime_type: str | None = None,
        name: str | None = None,
        *,
        size_bytes: int | None = None,
        sha256: str | None = None,
        metadata: dict[str, typing.Any] | None = None,
        content_base64: str | None = None,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create an artifact.created result.

        Runner created an artifact that should be persisted by Host.

        Args:
            run_id: Run identifier (must match current run)
            artifact_id: Unique artifact identifier (recommended: UUID v4)
            artifact_type: Type of artifact ('image', 'file', 'voice', 'tool_result', etc.)
            mime_type: MIME type of the content
            name: Original file name
            size_bytes: Size in bytes
            sha256: SHA256 hash of content
            metadata: Additional metadata (platform-specific info, etc.)
            content_base64: Base64-encoded content for small artifacts.
                For large artifacts, use external storage and omit this field.
                Host will decode and store in BinaryStorage.

        Returns:
            AgentRunResult with type="artifact.created"

        Note:
            - Host sets conversation_id, run_id, runner_id from current context.
            - Do NOT pass conversation_id/run_id in data; Host ignores them for security.
            - For large artifacts (>1MB), consider using external storage and omitting content_base64.
        """
        if not artifact_type:
            raise ValueError("artifact_type is required")

        payload = ArtifactCreatedPayload(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            mime_type=mime_type,
            name=name,
            size_bytes=size_bytes,
            sha256=sha256,
            metadata=metadata,
            content_base64=content_base64,
        )

        return cls(
            run_id=run_id,
            type=AgentRunResultType.ARTIFACT_CREATED,
            data=payload.model_dump(mode="json", exclude_none=True),
            sequence=sequence,
            timestamp=timestamp,
        )

    @classmethod
    def state_updated(
        cls,
        run_id: str,
        key: str,
        value: typing.Any,
        scope: STATE_SCOPE_LITERAL,
        *,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create a state.updated result.

        Runner requests host to persist a state change.
        SDK defines the protocol; LangBot host handles actual persistence.

        Args:
            run_id: Run identifier
            key: State key, should use namespace prefix (e.g., external.conversation_id)
            value: State value, must be JSON-serializable
            scope: State scope - one of: conversation, actor, subject, runner.

        Returns:
            AgentRunResult with type="state.updated" and data containing scope/key/value.

        Raises:
            ValueError: If scope is not one of the valid scopes.

        Example:
            # Store external platform conversation ID
            yield AgentRunResult.state_updated(
                run_id,
                "external.conversation_id",
                "abc123",
                scope="conversation"
            )

            # Store user preference
            yield AgentRunResult.state_updated(
                run_id,
                "preferred_language",
                "en",
                scope="actor",
            )
        """
        if scope not in VALID_STATE_SCOPES:
            raise ValueError(
                f"Invalid scope '{scope}'. Must be one of: {', '.join(VALID_STATE_SCOPES)}"
            )

        payload = StateUpdatedPayload(scope=scope, key=key, value=value)

        return cls(
            run_id=run_id,
            type=AgentRunResultType.STATE_UPDATED,
            data=payload.model_dump(mode="json"),
            sequence=sequence,
            timestamp=timestamp,
        )

    @classmethod
    def run_completed(
        cls,
        run_id: str,
        message: Message | None = None,
        finish_reason: str = "stop",
        *,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create a run.completed result.

        If message is provided, LangBot can map it to final Message.
        If message.completed was already output, message can be None.
        """
        payload = RunCompletedPayload(finish_reason=finish_reason, message=message)
        return cls(
            run_id=run_id,
            type=AgentRunResultType.RUN_COMPLETED,
            data=payload.model_dump(mode="json", exclude_none=True),
            sequence=sequence,
            timestamp=timestamp,
        )

    @classmethod
    def run_failed(
        cls,
        run_id: str,
        error: str,
        code: str | None = None,
        retryable: bool = False,
        *,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create a run.failed result.

        LangBot returns a user-friendly error message per host delivery strategy.
        """
        payload = RunFailedPayload(
            error=error,
            code=code or "runner.error",
            retryable=retryable,
        )
        return cls(
            run_id=run_id,
            type=AgentRunResultType.RUN_FAILED,
            data=payload.model_dump(mode="json"),
            sequence=sequence,
            timestamp=timestamp,
        )

    @classmethod
    def action_requested(
        cls,
        run_id: str,
        action: str,
        target: dict[str, typing.Any] | None = None,
        payload: dict[str, typing.Any] | None = None,
        *,
        sequence: int | None = None,
        timestamp: int | None = None,
    ) -> "AgentRunResult":
        """Create an action.requested result.

        This phase only logs to telemetry, actual execution waits for EBA.
        """
        result_payload = ActionRequestedPayload(
            action=action,
            target=target,
            payload=payload,
        )
        return cls(
            run_id=run_id,
            type=AgentRunResultType.ACTION_REQUESTED,
            data=result_payload.model_dump(mode="json"),
            sequence=sequence,
            timestamp=timestamp,
        )
