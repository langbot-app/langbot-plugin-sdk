"""Invocation-local tracing for Runner context APIs."""

import asyncio
import uuid
from contextlib import asynccontextmanager, suppress
from typing import Any
from langbot_plugin.api.entities.builtin.runner.result import RunnerResult
from langbot_plugin.api.proxies.runner.api import RunnerAPIProxy


class _TracedRunAPI:
    """Delegate authorized APIs and stream tool delivery attempts and outcomes."""

    def __init__(self, api: RunnerAPIProxy, run_id: str, results: asyncio.Queue):
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
            RunnerResult.tool_call_started(
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
                RunnerResult.tool_call_completed(
                    self._run_id,
                    call_id,
                    tool_name,
                    error=str(exc),
                )
            )
            raise
        await self._results.put(
            RunnerResult.tool_call_completed(
                self._run_id,
                call_id,
                tool_name,
                result=result,
            )
        )
        return result

    @asynccontextmanager
    async def reply_stream(self):
        """Stream one explicit reply; update() accepts the full text so far."""
        call_id = str(uuid.uuid4())
        await self._results.put(
            RunnerResult.tool_call_started(
                self._run_id, call_id, "event_reply", {"stream": True}
            )
        )
        try:
            async with self._api.reply_stream() as stream:
                yield stream
        except BaseException as exc:
            with suppress(asyncio.QueueFull):
                self._results.put_nowait(
                    RunnerResult.tool_call_completed(
                        self._run_id,
                        call_id,
                        "event_reply",
                        error=str(exc) or type(exc).__name__,
                    )
                )
            raise
        else:
            await self._results.put(
                RunnerResult.tool_call_completed(
                    self._run_id, call_id, "event_reply", result=stream.result
                )
            )
