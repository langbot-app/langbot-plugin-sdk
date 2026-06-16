"""Run-scoped LangBot tools exposed to external harnesses."""

from __future__ import annotations

import json
import typing
import copy

import pydantic

from langbot_plugin.api.agent_tools.decorators import agent_tool, collect_agent_tools
from langbot_plugin.api.agent_tools.decorators import AgentToolSpec
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.proxies.agent_run_api import AgentRunAPIProxy


class EmptyArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")


class ListAssetsArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    asset_types: list[
        typing.Literal[
            "event",
            "history",
            "knowledge_bases",
            "tools",
            "mcp_tools",
        ]
    ] = pydantic.Field(default_factory=list)
    include_schemas: bool = False


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


class GetToolDetailArgs(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    tool_name: str


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


def _operation_allowed(operations: list[str], operation: str) -> bool:
    return not operations or operation in operations


def _with_optional_run_token(tool: dict[str, typing.Any]) -> dict[str, typing.Any]:
    data = copy.deepcopy(tool)
    schema = data.setdefault("inputSchema", {})
    if not isinstance(schema, dict):
        schema = {}
        data["inputSchema"] = schema
    properties = schema.setdefault("properties", {})
    if not isinstance(properties, dict):
        properties = {}
        schema["properties"] = properties
    properties.setdefault(
        "run_token",
        {
            "type": "string",
            "description": (
                "Short-lived LangBot run token. Optional when the MCP request "
                "already includes an Authorization bearer token."
            ),
        },
    )
    return data


class AgentRunExternalTools:
    """Annotated tool surface backed by AgentRunAPIProxy."""

    def __init__(self, api: AgentRunAPIProxy, ctx: AgentRunContext) -> None:
        self.api = api
        self.ctx = ctx
        self._tools = collect_agent_tools(self)

    @classmethod
    def all_mcp_tools(
        cls, *, include_run_token: bool = False
    ) -> list[dict[str, typing.Any]]:
        tools: list[dict[str, typing.Any]] = []
        seen: set[str] = set()
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            spec = getattr(attr, "__langbot_agent_tool__", None)
            if not isinstance(spec, AgentToolSpec):
                continue
            if spec.name in seen:
                raise ValueError(f"Duplicate Agent tool name: {spec.name}")
            seen.add(spec.name)
            tools.append(spec.to_mcp_tool())
        if include_run_token:
            return [_with_optional_run_token(tool) for tool in tools]
        return tools

    def _available_tool_names(self) -> set[str]:
        names = {"langbot_get_current_event", "langbot_list_assets"}

        available_apis = self.ctx.context.available_apis
        if available_apis.history_page:
            names.add("langbot_history_page")
        if any(
            _operation_allowed(item.operations, "retrieve")
            for item in self.ctx.resources.knowledge_bases
        ):
            names.add("langbot_retrieve_knowledge")
        if any(
            _operation_allowed(item.operations, "detail")
            for item in self.ctx.resources.tools
        ):
            names.add("langbot_get_tool_detail")
        if any(
            _operation_allowed(item.operations, "call")
            for item in self.ctx.resources.tools
        ):
            names.add("langbot_call_tool")

        return names

    def mcp_tools(
        self,
        *,
        include_unavailable: bool = False,
        include_run_token: bool = False,
    ) -> list[dict[str, typing.Any]]:
        available_names = (
            self._available_tool_names() if not include_unavailable else None
        )
        tools = [
            tool.spec.to_mcp_tool()
            for name, tool in self._tools.items()
            if available_names is None or name in available_names
        ]
        if include_run_token:
            return [_with_optional_run_token(tool) for tool in tools]
        return tools

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

        structured = _dump_jsonable(result)
        if not isinstance(structured, dict):
            structured = {"result": structured}
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(structured, ensure_ascii=False),
                }
            ],
            "structuredContent": structured,
        }

    def _asset_summary(
        self,
        *,
        asset_types: list[str] | None = None,
        include_schemas: bool = False,
    ) -> dict[str, typing.Any]:
        requested = set(asset_types or [])
        include_all = not requested

        data: dict[str, typing.Any] = {
            "run_id": self.ctx.run_id,
            "asset_types": sorted(
                requested
                or {
                    "event",
                    "history",
                    "knowledge_bases",
                    "tools",
                    "mcp_tools",
                }
            ),
        }
        if include_all or "event" in requested:
            data["event"] = {
                "available": True,
                "tool_name": "langbot_get_current_event",
            }
        if include_all or "history" in requested:
            data["history"] = {
                "available": bool(self.ctx.context.available_apis.history_page),
                "tool_name": "langbot_history_page",
            }
        if include_all or "knowledge_bases" in requested:
            data["knowledge_bases"] = [
                {
                    "kb_id": item.kb_id,
                    "name": item.kb_name,
                    "type": item.kb_type,
                    "operations": list(item.operations),
                }
                for item in self.ctx.resources.knowledge_bases
            ]
        if include_all or "tools" in requested:
            data["tools"] = [
                {
                    "tool_name": item.tool_name,
                    "type": item.tool_type,
                    "description": item.description,
                    "operations": list(item.operations),
                }
                for item in self.ctx.resources.tools
            ]
        if include_all or "mcp_tools" in requested:
            data["mcp_tools"] = [
                {
                    "tool_name": tool["name"],
                    "description": tool.get("description"),
                    **(
                        {"schema": tool.get("inputSchema", {})}
                        if include_schemas
                        else {}
                    ),
                }
                for tool in self.mcp_tools()
            ]
        return data

    @agent_tool(
        name="langbot_list_assets",
        description="List the LangBot event, history, knowledge bases, tools, and MCP bridge tools authorized for the current run.",
        args_model=ListAssetsArgs,
        read_only=True,
    )
    async def list_assets(self, args: ListAssetsArgs) -> dict[str, typing.Any]:
        return self._asset_summary(
            asset_types=args.asset_types,
            include_schemas=args.include_schemas,
        )

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
        name="langbot_get_tool_detail",
        description="Return the parameter schema and description for an authorized LangBot tool in the current run.",
        args_model=GetToolDetailArgs,
        read_only=True,
    )
    async def get_tool_detail(self, args: GetToolDetailArgs) -> dict[str, typing.Any]:
        return await self.api.get_tool_detail(tool_name=args.tool_name)

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
