"""Explicitly bound, code-defined EBA event processors."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress, asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable

from langbot_plugin.api.definition.components.agent_runner.runner import AgentRunner
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.result import (
    AgentRunResult,
    ProcessorLogPayload,
)
from langbot_plugin.api.entities.builtin.platform.events import (
    EBAEvent,
    parse_eba_event,
)
from langbot_plugin.api.proxies.agent_run import AgentRunAPIProxy


class _TracedRunAPI:
    """Delegate authorized APIs and stream tool delivery attempts and outcomes."""

    def __init__(self, api: AgentRunAPIProxy, run_id: str, results: asyncio.Queue):
        self._api = api
        self._run_id = run_id
        self._results = results

    def __getattr__(self, name):
        return getattr(self._api, name)

    async def call_tool(
        self, tool_name: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        call_id = str(uuid.uuid4())
        await self._results.put(
            AgentRunResult.tool_call_started(
                self._run_id,
                call_id,
                tool_name,
                parameters,
            )
        )
        try:
            result = await self._api.call_tool(tool_name, parameters)
        except Exception as exc:
            await self._results.put(
                AgentRunResult.tool_call_completed(
                    self._run_id,
                    call_id,
                    tool_name,
                    error=str(exc),
                )
            )
            raise
        await self._results.put(
            AgentRunResult.tool_call_completed(
                self._run_id,
                call_id,
                tool_name,
                result=result,
            )
        )
        return result


@dataclass
class EventProcessorContext:
    """One event invocation, with no fabricated Pipeline Query."""

    event: EBAEvent
    run_id: str
    config: dict[str, Any]
    api: _TracedRunAPI
    _results: asyncio.Queue[AgentRunResult]

    async def reply(self, text: str) -> dict[str, Any]:
        """Reply to the current event through the authorized Host action API."""
        return await self.api.call_tool("event_reply", {"text": text})

    @asynccontextmanager
    async def reply_stream(self):
        """Stream one explicit reply; update() accepts the full text so far."""
        call_id = str(uuid.uuid4())
        await self._results.put(
            AgentRunResult.tool_call_started(
                self.run_id, call_id, "event_reply", {"stream": True}
            )
        )
        try:
            async with self.api.reply_stream() as stream:
                yield stream
        except BaseException as exc:
            with suppress(asyncio.QueueFull):
                self._results.put_nowait(
                    AgentRunResult.tool_call_completed(
                        self.run_id,
                        call_id,
                        "event_reply",
                        error=str(exc) or type(exc).__name__,
                    )
                )
            raise
        else:
            await self._results.put(
                AgentRunResult.tool_call_completed(
                    self.run_id, call_id, "event_reply", result=stream.result
                )
            )

    async def log(self, text: str, level: str = "info") -> None:
        """Record an invocation log without sending a platform message."""
        if level not in {"debug", "info", "warning", "error"}:
            raise ValueError("Invalid log level")
        await self._results.put(
            AgentRunResult(
                run_id=self.run_id,
                type="processor.log",
                data=ProcessorLogPayload(text=str(text), level=level).model_dump(),
            )
        )


class EventProcessor(AgentRunner):
    """Code handlers using the shared run transport, without an Agent loop.

    This is a distinct component kind. It never participates in EventListener
    broadcast and is invoked only through a Host-created processor instance.
    """

    __kind__ = "EventProcessor"

    def __init__(self):
        super().__init__()
        self.registered_handlers: dict[
            type[EBAEvent], list[Callable[[EventProcessorContext], Awaitable[None]]]
        ] = {}

    def handler(self, event_type: type[EBAEvent]):
        """Register a typed EBA handler using the familiar listener syntax."""
        if not isinstance(event_type, type) or not issubclass(event_type, EBAEvent):
            raise TypeError("EventProcessor handlers require EBA event types")

        def decorator(callback):
            self.registered_handlers.setdefault(event_type, []).append(callback)
            return callback

        return decorator

    async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunResult, None]:
        event = parse_eba_event(ctx.event.data)
        callbacks = self.registered_handlers.get(
            type(event)
        ) or self.registered_handlers.get(EBAEvent)
        if not callbacks:
            raise ValueError(f"No handler registered for {event.type}")
        results: asyncio.Queue[AgentRunResult] = asyncio.Queue(maxsize=256)
        event_context = EventProcessorContext(
            event=event,
            run_id=ctx.run_id,
            config=dict(ctx.config),
            api=_TracedRunAPI(self.get_run_api(ctx), ctx.run_id, results),
            _results=results,
        )

        async def execute():
            for callback in callbacks:
                await callback(event_context)

        task = asyncio.create_task(execute())
        next_result = None
        try:
            while not task.done():
                next_result = asyncio.create_task(results.get())
                done, _ = await asyncio.wait(
                    {task, next_result}, return_when=asyncio.FIRST_COMPLETED
                )
                if next_result in done:
                    yield next_result.result()
                    next_result = None
                else:
                    next_result.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_result
                    next_result = None
            while not results.empty():
                yield results.get_nowait()
            await task
            yield AgentRunResult.run_completed(ctx.run_id)
        finally:
            for pending in (next_result, task):
                if pending is not None:
                    pending.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await pending
