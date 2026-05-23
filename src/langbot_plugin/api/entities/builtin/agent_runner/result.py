"""AgentRunResult as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic
import enum

from langbot_plugin.api.entities.builtin.provider.message import Message, MessageChunk
from langbot_plugin.api.entities.builtin.agent_runner.state import VALID_STATE_SCOPES, STATE_SCOPE_LITERAL


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


class AgentRunResult(pydantic.BaseModel):
    """Result event from AgentRunner.run().

    Protocol v1 result structure:
    - run_id: Links result to the run
    - type: Result type
    - data: Type-specific payload
    - sequence: Optional sequence number for ordering
    - timestamp: Optional timestamp

    Each yield from the runner's run() method produces one AgentRunResult.
    LangBot maps these to appropriate pipeline events.
    """

    run_id: str
    """Run identifier linking this result to the run."""

    type: AgentRunResultType
    """Result type."""

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
    ) -> "AgentRunResult":
        """Create a message.delta result.

        LangBot maps this to MessageChunk for streaming output.
        """
        return cls(
            run_id=run_id,
            type=AgentRunResultType.MESSAGE_DELTA,
            data={"chunk": chunk.model_dump(mode="json")},
        )

    @classmethod
    def message_completed(
        cls,
        run_id: str,
        message: Message,
    ) -> "AgentRunResult":
        """Create a message.completed result.

        LangBot maps this to a complete Message.
        """
        return cls(
            run_id=run_id,
            type=AgentRunResultType.MESSAGE_COMPLETED,
            data={"message": message.model_dump(mode="json")},
        )

    @classmethod
    def tool_call_started(
        cls,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        parameters: dict[str, typing.Any],
    ) -> "AgentRunResult":
        """Create a tool.call.started result.

        LangBot records this for telemetry/debug.
        """
        return cls(
            run_id=run_id,
            type=AgentRunResultType.TOOL_CALL_STARTED,
            data={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "parameters": parameters,
            },
        )

    @classmethod
    def tool_call_completed(
        cls,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        result: dict[str, typing.Any] | None = None,
        error: str | None = None,
    ) -> "AgentRunResult":
        """Create a tool.call.completed result.

        LangBot records this for telemetry/debug.
        """
        return cls(
            run_id=run_id,
            type=AgentRunResultType.TOOL_CALL_COMPLETED,
            data={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "result": result,
                "error": error,
            },
        )

    @classmethod
    def artifact_created(
        cls,
        run_id: str,
        artifact_id: str,
        artifact_type: str,
        mime_type: str | None = None,
        size: int | None = None,
        name: str | None = None,
        *,
        size_bytes: int | None = None,
        sha256: str | None = None,
        metadata: dict[str, typing.Any] | None = None,
        content_base64: str | None = None,
    ) -> "AgentRunResult":
        """Create an artifact.created result.

        Runner created an artifact that should be persisted by Host.

        Args:
            run_id: Run identifier (must match current run)
            artifact_id: Unique artifact identifier (recommended: UUID v4)
            artifact_type: Type of artifact ('image', 'file', 'voice', 'tool_result', etc.)
            mime_type: MIME type of the content
            size: (Deprecated) Use size_bytes instead
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
        # Handle backward compatibility: size -> size_bytes
        if size_bytes is None and size is not None:
            size_bytes = size

        data: dict[str, typing.Any] = {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
        }

        # Optional fields
        if mime_type is not None:
            data["mime_type"] = mime_type
        if name is not None:
            data["name"] = name
        if size_bytes is not None:
            data["size_bytes"] = size_bytes
        if sha256 is not None:
            data["sha256"] = sha256
        if metadata is not None:
            data["metadata"] = metadata
        if content_base64 is not None:
            data["content_base64"] = content_base64

        return cls(
            run_id=run_id,
            type=AgentRunResultType.ARTIFACT_CREATED,
            data=data,
        )

    @classmethod
    def state_updated(
        cls,
        run_id: str,
        key: str,
        value: typing.Any,
        scope: STATE_SCOPE_LITERAL = "conversation",
    ) -> "AgentRunResult":
        """Create a state.updated result.

        Runner requests host to persist a state change.
        SDK defines the protocol; LangBot host handles actual persistence.

        Args:
            run_id: Run identifier
            key: State key, should use namespace prefix (e.g., external.conversation_id)
            value: State value, must be JSON-serializable
            scope: State scope - one of: conversation, actor, subject, runner.
                Defaults to "conversation" for backward compatibility.

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

            # Store user preference (backward compatible)
            yield AgentRunResult.state_updated(run_id, "preferred_language", "en")
        """
        if scope not in VALID_STATE_SCOPES:
            raise ValueError(
                f"Invalid scope '{scope}'. Must be one of: {', '.join(VALID_STATE_SCOPES)}"
            )

        return cls(
            run_id=run_id,
            type=AgentRunResultType.STATE_UPDATED,
            data={"scope": scope, "key": key, "value": value},
        )

    @classmethod
    def run_completed(
        cls,
        run_id: str,
        message: Message | None = None,
        finish_reason: str = "stop",
    ) -> "AgentRunResult":
        """Create a run.completed result.

        If message is provided, LangBot can map it to final Message.
        If message.completed was already output, message can be None.
        """
        data: dict[str, typing.Any] = {"finish_reason": finish_reason}
        if message is not None:
            data["message"] = message.model_dump(mode="json")
        return cls(run_id=run_id, type=AgentRunResultType.RUN_COMPLETED, data=data)

    @classmethod
    def run_failed(
        cls,
        run_id: str,
        error: str,
        code: str | None = None,
        retryable: bool = False,
    ) -> "AgentRunResult":
        """Create a run.failed result.

        LangBot returns user-friendly error message per pipeline error strategy.
        """
        return cls(
            run_id=run_id,
            type=AgentRunResultType.RUN_FAILED,
            data={
                "error": error,
                "code": code or "runner.error",
                "retryable": retryable,
            },
        )

    @classmethod
    def action_requested(
        cls,
        run_id: str,
        action: str,
        target: dict[str, typing.Any] | None = None,
        payload: dict[str, typing.Any] | None = None,
    ) -> "AgentRunResult":
        """Create an action.requested result.

        This phase only logs to telemetry, actual execution waits for EBA.
        """
        return cls(
            run_id=run_id,
            type=AgentRunResultType.ACTION_REQUESTED,
            data={
                "action": action,
                "target": target,
                "payload": payload,
            },
        )