"""AgentRunResult as defined in Protocol v1."""

from __future__ import annotations

import typing
import pydantic
import enum

from langbot_plugin.api.entities.builtin.provider.message import Message, MessageChunk


class AgentRunResultType(str, enum.Enum):
    """Type of AgentRunResult event."""

    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    STATE_UPDATED = "state.updated"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    ACTION_REQUESTED = "action.requested"


class AgentRunResult(pydantic.BaseModel):
    """Result event from AgentRunner.run().

    Each yield from the runner's run() method produces one AgentRunResult.
    LangBot maps these to appropriate pipeline events.
    """

    type: AgentRunResultType
    """Result type."""

    data: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Result data."""

    @classmethod
    def message_delta(cls, chunk: MessageChunk) -> "AgentRunResult":
        """Create a message.delta result.

        LangBot maps this to MessageChunk for streaming output.
        """
        return cls(
            type=AgentRunResultType.MESSAGE_DELTA,
            data={"chunk": chunk.model_dump(mode="json")},
        )

    @classmethod
    def message_completed(cls, message: Message) -> "AgentRunResult":
        """Create a message.completed result.

        LangBot maps this to a complete Message.
        """
        return cls(
            type=AgentRunResultType.MESSAGE_COMPLETED,
            data={"message": message.model_dump(mode="json")},
        )

    @classmethod
    def tool_call_started(
        cls,
        tool_call_id: str,
        tool_name: str,
        parameters: dict[str, typing.Any],
    ) -> "AgentRunResult":
        """Create a tool.call.started result.

        LangBot records this for telemetry/debug.
        """
        return cls(
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
        tool_call_id: str,
        tool_name: str,
        result: dict[str, typing.Any] | None = None,
        error: str | None = None,
    ) -> "AgentRunResult":
        """Create a tool.call.completed result.

        LangBot records this for telemetry/debug.
        """
        return cls(
            type=AgentRunResultType.TOOL_CALL_COMPLETED,
            data={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "result": result,
                "error": error,
            },
        )

    @classmethod
    def state_updated(cls, key: str, value: typing.Any) -> "AgentRunResult":
        """Create a state.updated result.

        LangBot records this but does not auto-persist.
        Official plugins should use plugin storage instead.
        """
        return cls(
            type=AgentRunResultType.STATE_UPDATED,
            data={"key": key, "value": value},
        )

    @classmethod
    def run_completed(
        cls,
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
        return cls(type=AgentRunResultType.RUN_COMPLETED, data=data)

    @classmethod
    def run_failed(
        cls,
        error: str,
        code: str | None = None,
        retryable: bool = False,
    ) -> "AgentRunResult":
        """Create a run.failed result.

        LangBot returns user-friendly error message per pipeline error strategy.
        """
        return cls(
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
        action: str,
        parameters: dict[str, typing.Any],
    ) -> "AgentRunResult":
        """Create an action.requested result.

        This phase only logs to telemetry, actual execution waits for EBA.
        """
        return cls(
            type=AgentRunResultType.ACTION_REQUESTED,
            data={"action": action, "parameters": parameters},
        )
