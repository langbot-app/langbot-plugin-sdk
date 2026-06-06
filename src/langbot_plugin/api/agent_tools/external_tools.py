"""Run-scoped LangBot tools exposed to external harnesses."""

from __future__ import annotations

import json
import typing

import pydantic

from langbot_plugin.api.agent_tools.decorators import agent_tool, collect_agent_tools
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.proxies.agent_run_api import AgentRunAPIProxy


class EmptyArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")


class HistoryPageArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    conversation_id: str | None = None
    before_cursor: str | None = None
    after_cursor: str | None = None
    limit: int = pydantic.Field(default=50, ge=1, le=100)
    direction: str = pydantic.Field(default="backward", pattern="^(backward|forward)$")
    include_artifacts: bool = False


class RetrieveKnowledgeArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    kb_id: str
    query_text: str | None = None
    query: str | None = None
    top_k: int = pydantic.Field(default=5, ge=1, le=20)
    filters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


class CallToolArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    tool_name: str
    parameters: dict[str, typing.Any] = pydantic.Field(default_factory=dict)


def _dump_jsonable(value: typing.Any) -> typing.Any:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _dump_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class AgentRunExternalTools:
    """Annotated tool surface backed by AgentRunAPIProxy."""

    def __init__(self, api: AgentRunAPIProxy, ctx: AgentRunContext) -> None:
        self.api = api
        self.ctx = ctx
        self._tools = collect_agent_tools(self)

    def _available_tool_names(self) -> set[str]:
        names = {"langbot_get_current_event"}

        available_apis = self.ctx.context.available_apis
        if available_apis.history_page:
            names.add("langbot_history_page")
        if self.ctx.resources.knowledge_bases:
            names.add("langbot_retrieve_knowledge")
        if self.ctx.resources.tools:
            names.add("langbot_call_tool")

        return names

    def mcp_tools(self) -> list[dict[str, typing.Any]]:
        available_names = self._available_tool_names()
        return [
            tool.spec.to_mcp_tool()
            for name, tool in self._tools.items()
            if name in available_names
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, typing.Any] | None = None
    ) -> typing.Any:
        tool = self._tools.get(name) if name in self._available_tool_names() else None
        if tool is None:
            raise ValueError(f"Unknown LangBot external tool: {name}")
        args = tool.spec.args_model.model_validate(arguments or {})
        return await tool.handler(args)

    async def call_mcp_tool(
        self, name: str, arguments: dict[str, typing.Any] | None = None
    ) -> dict[str, typing.Any]:
        try:
            result = await self.call_tool(name, arguments)
        except Exception as e:
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": str(e),
                    }
                ],
            }

        structured = result if isinstance(result, dict) else {"result": result}
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False),
                }
            ],
            "structuredContent": structured,
        }

    @agent_tool(
        name="langbot_get_current_event",
        description="Return the current LangBot event, input, actor, subject, resources, context, state, and runtime snapshot.",
        args_model=EmptyArgs,
        read_only=True,
    )
    async def get_current_event(self, args: EmptyArgs) -> dict[str, typing.Any]:
        input_value = self.ctx.input
        input_text = ""
        if input_value is not None:
            to_text = getattr(input_value, "to_text", None)
            if callable(to_text):
                input_text = to_text()
            else:
                input_text = getattr(input_value, "text", "") or ""

        return {
            "run_id": self.ctx.run_id,
            "trigger": _dump_jsonable(self.ctx.trigger),
            "event": _dump_jsonable(self.ctx.event),
            "conversation": _dump_jsonable(self.ctx.conversation),
            "actor": _dump_jsonable(self.ctx.actor),
            "subject": _dump_jsonable(self.ctx.subject),
            "input": {
                "text": input_text,
                "attachments": _dump_jsonable(getattr(input_value, "attachments", [])),
                "contents": _dump_jsonable(getattr(input_value, "contents", [])),
            },
            "resources": _dump_jsonable(self.ctx.resources),
            "context": _dump_jsonable(self.ctx.context),
            "state": _dump_jsonable(self.ctx.state),
            "runtime": _dump_jsonable(self.ctx.runtime),
        }

    @agent_tool(
        name="langbot_history_page",
        description="Page through authorized LangBot conversation history for the current run.",
        args_model=HistoryPageArgs,
        read_only=True,
    )
    async def history_page(self, args: HistoryPageArgs) -> dict[str, typing.Any]:
        return await self.api.history_page(
            conversation_id=args.conversation_id,
            before_cursor=args.before_cursor,
            after_cursor=args.after_cursor,
            limit=args.limit,
            direction=args.direction,
            include_artifacts=args.include_artifacts,
        )

    @agent_tool(
        name="langbot_retrieve_knowledge",
        description="Retrieve documents from an authorized LangBot knowledge base for the current run.",
        args_model=RetrieveKnowledgeArgs,
        read_only=True,
    )
    async def retrieve_knowledge(
        self, args: RetrieveKnowledgeArgs
    ) -> list[dict[str, typing.Any]]:
        query_text = (args.query_text or args.query or "").strip()
        if not query_text:
            raise ValueError("query_text is required")
        return await self.api.retrieve_knowledge(
            kb_id=args.kb_id,
            query_text=query_text,
            top_k=args.top_k,
            filters=args.filters,
        )

    @agent_tool(
        name="langbot_call_tool",
        description="Call an authorized LangBot tool for the current run.",
        args_model=CallToolArgs,
    )
    async def call_langbot_tool(self, args: CallToolArgs) -> dict[str, typing.Any]:
        return await self.api.call_tool(
            tool_name=args.tool_name,
            parameters=args.parameters,
        )
