"""AgentRun API Proxy for AgentRunner components.

This proxy provides a restricted API for AgentRunner execution,
with all capabilities explicitly authorized through ctx.resources.

Uses composition + delegation pattern:
- Composes LangBotAPIProxy for actual API calls (reduces code duplication)
- Adds permission validation before each delegated call
- Only exposes APIs that are authorized for the current run
"""

from __future__ import annotations

import base64
from typing import Any

from langbot_plugin.runtime.io.handler import Handler
from langbot_plugin.entities.io.errors import (
    ActionCallError,
    ActionCallTimeoutError,
    ConnectionClosedError,
)
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.api.entities.builtin.provider import message as provider_message
from langbot_plugin.api.entities.builtin.resource import tool as resource_tool
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.page_results import (
    AgentEventRecord,
    EventPage,
    HistoryPage,
    HistorySearchResult,
)
from langbot_plugin.api.entities.builtin.agent_runner.run_ledger import (
    AgentRun,
    AgentRunEvent,
    AgentRuntime,
    RunEventPage,
    RunPage,
    RunnerStatsPage,
    RunStats,
    RuntimePage,
    RuntimeStats,
)
from langbot_plugin.api.entities.builtin.agent_runner.result import AgentRunResult
from langbot_plugin.api.entities.builtin.agent_runner.errors import (
    AgentAPIError,
    AgentAPIException,
)
from langbot_plugin.api.entities.builtin.agent_runner.steering import (
    SteeringPullResult,
)
from langbot_plugin.api.proxies.langbot_api import LangBotAPIProxy
from langbot_plugin.utils.deadline import remaining_deadline_seconds


DEFAULT_RESOURCE_OPERATIONS: dict[str, frozenset[str]] = {
    "model": frozenset({"invoke", "stream", "rerank"}),
    "tool": frozenset({"detail", "call"}),
    "knowledge_base": frozenset({"list", "retrieve"}),
}


class PermissionDeniedError(Exception):
    """Raised when an API call is not authorized by ctx.resources."""

    pass


def _build_agent_api_exception(
    action: PluginToRuntimeAction,
    error: ActionCallError,
) -> AgentAPIException:
    data = error.data or {}
    raw_error = data.get("error") if isinstance(data, dict) else None
    if isinstance(raw_error, dict):
        try:
            return AgentAPIException(AgentAPIError.model_validate(raw_error))
        except Exception:
            pass
    if isinstance(data, dict) and {"code", "message"}.issubset(data.keys()):
        try:
            return AgentAPIException(AgentAPIError.model_validate(data))
        except Exception:
            pass
    return AgentAPIException(
        AgentAPIError(
            code="host.action_error",
            message=str(error),
            retryable=False,
            details={"action": action.value, "response_data": data},
        )
    )


def _build_transport_api_exception(
    action: PluginToRuntimeAction,
    error: ActionCallTimeoutError | ConnectionClosedError,
) -> AgentAPIException:
    if isinstance(error, ActionCallTimeoutError):
        return AgentAPIException(
            AgentAPIError(
                code="deadline_exceeded",
                message=str(error),
                retryable=True,
                details={"action": action.value},
            )
        )
    return AgentAPIException(
        AgentAPIError(
            code="runtime_error",
            message=str(error),
            retryable=True,
            details={"action": action.value},
        )
    )


def _build_deadline_exceeded_exception() -> AgentAPIException:
    return AgentAPIException(
        AgentAPIError(
            code="deadline_exceeded",
            message="Agent run deadline has expired",
            retryable=True,
        )
    )


class _AgentRunHandlerAdapter:
    """Wrap Handler errors in AgentAPIException for runner-facing APIs."""

    def __init__(self, handler: Handler):
        self._handler = handler

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handler, name)

    async def call_action(
        self,
        action: PluginToRuntimeAction,
        data: dict[str, Any],
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        try:
            return await self._handler.call_action(action, data, timeout)
        except ActionCallError as error:
            raise _build_agent_api_exception(action, error) from error
        except (ActionCallTimeoutError, ConnectionClosedError) as error:
            raise _build_transport_api_exception(action, error) from error

    async def call_action_generator(
        self,
        action: PluginToRuntimeAction,
        data: dict[str, Any],
        timeout: float = 15.0,
    ):
        try:
            async for item in self._handler.call_action_generator(
                action, data, timeout
            ):
                yield item
        except ActionCallError as error:
            raise _build_agent_api_exception(action, error) from error
        except (ActionCallTimeoutError, ConnectionClosedError) as error:
            raise _build_transport_api_exception(action, error) from error


class AgentRunAPIProxy:
    """Restricted API proxy for AgentRunner execution.

    Uses COMPOSITION + DELEGATION to LangBotAPIProxy:
    - Validates run-scoped authorization before delegating calls
    - Reduces code duplication by reusing LangBotAPIProxy implementation
    - Only exposes authorized APIs (hasattr returns False for unauthorized methods)

    Authorized APIs (validated against ctx.resources):
    - invoke_llm() / invoke_llm_stream(): requires model in ctx.resources.models
    - get_tool_detail() / call_tool(): requires tool_name in ctx.resources.tools
    - retrieve_knowledge(): requires kb_id in ctx.resources.knowledge_bases
    - plugin_storage: requires ctx.resources.storage.plugin_storage=True
    - workspace_storage: requires ctx.resources.storage.workspace_storage=True

    Helper methods (local read from ctx.resources):
    - get_allowed_models(): returns ctx.resources.models
    - get_allowed_tools(): returns ctx.resources.tools
    - get_allowed_knowledge_bases(): returns ctx.resources.knowledge_bases

    Additional APIs (AgentRunner-specific):
    - invoke_rerank(): requires rerank model authorization in ctx.resources

    Not available (platform actions, use AgentRunResult.action_requested instead):
    - get_bots() / get_bot_info() / send_message()
    - list_tools() / list_knowledge_bases() / get_llm_models()
    - vector_upsert() / vector_search() / invoke_embedding()
    """

    ctx: AgentRunContext
    """Agent run context containing run_id, resources, and runtime info."""

    _api: LangBotAPIProxy
    """Unrestricted API proxy for delegation (composition)."""

    # Pre-computed allowed IDs for efficient O(1) validation
    _allowed_model_ids: frozenset[str]
    _allowed_tool_names: frozenset[str]
    _allowed_kb_ids: frozenset[str]
    _allowed_model_operations: dict[str, frozenset[str]]
    _allowed_tool_operations: dict[str, frozenset[str]]
    _allowed_kb_operations: dict[str, frozenset[str]]

    def __init__(self, ctx: AgentRunContext, plugin_runtime_handler: Handler):
        self.ctx = ctx
        self._api = LangBotAPIProxy(_AgentRunHandlerAdapter(plugin_runtime_handler))
        # Pre-compute allowed IDs for efficient validation
        self._allowed_model_ids = frozenset(m.model_id for m in ctx.resources.models)
        self._allowed_tool_names = frozenset(t.tool_name for t in ctx.resources.tools)
        self._allowed_kb_ids = frozenset(k.kb_id for k in ctx.resources.knowledge_bases)
        self._allowed_model_operations = {
            m.model_id: self._normalize_operations("model", m.operations)
            for m in ctx.resources.models
        }
        self._allowed_tool_operations = {
            t.tool_name: self._normalize_operations("tool", t.operations)
            for t in ctx.resources.tools
        }
        self._allowed_kb_operations = {
            k.kb_id: self._normalize_operations("knowledge_base", k.operations)
            for k in ctx.resources.knowledge_bases
        }

    @property
    def run_id(self) -> str:
        """Unique identifier for this agent run."""
        return self.ctx.run_id

    def _remaining_deadline_seconds(self) -> float | None:
        return remaining_deadline_seconds(self.ctx.runtime.deadline_at)

    def _bounded_timeout(
        self,
        default: float,
        requested: float | None = None,
    ) -> float:
        base_timeout = default if requested is None else requested
        if not isinstance(base_timeout, (int, float)) or base_timeout <= 0:
            base_timeout = default

        remaining = self._remaining_deadline_seconds()
        if remaining is None:
            return float(base_timeout)
        if remaining <= 0:
            raise _build_deadline_exceeded_exception()
        return max(min(float(base_timeout), remaining), 0.001)

    def _context_api_enabled(self, name: str) -> bool:
        context = getattr(self.ctx, "context", None)
        if isinstance(context, dict):
            available_apis = context.get("available_apis")
        else:
            available_apis = getattr(context, "available_apis", None)

        if isinstance(available_apis, dict):
            return bool(available_apis.get(name, False))
        return bool(getattr(available_apis, name, False))

    def _require_context_api(self, name: str) -> None:
        if not self._context_api_enabled(name):
            raise PermissionDeniedError(f"{name} is not available for this run")

    def _expect_key(
        self,
        resp: dict[str, Any],
        key: str,
        action: PluginToRuntimeAction,
    ) -> Any:
        if key in resp:
            return resp[key]
        raise AgentAPIException(
            AgentAPIError(
                code="host.malformed_response",
                message=f"{action.value} response missing required field: {key}",
                retryable=False,
                details={"action": action.value, "missing_key": key},
            )
        )

    # ================= Resource Helper Methods =================

    def get_allowed_models(self) -> list[Any]:
        """Get the list of models authorized for this run."""
        return self.ctx.resources.models

    def get_allowed_tools(self) -> list[Any]:
        """Get the list of tools authorized for this run."""
        return self.ctx.resources.tools

    def get_allowed_knowledge_bases(self) -> list[Any]:
        """Get the list of knowledge bases authorized for this run."""
        return self.ctx.resources.knowledge_bases

    # ================= Permission Validation =================

    @staticmethod
    def _normalize_operations(
        resource_type: str, operations: list[str] | None
    ) -> frozenset[str]:
        if operations:
            return frozenset(str(operation) for operation in operations)
        return DEFAULT_RESOURCE_OPERATIONS[resource_type]

    @staticmethod
    def _validate_operation(
        resource_type: str,
        resource_id: str,
        operation: str,
        allowed_operations: frozenset[str] | None,
    ) -> None:
        effective_operations = (
            allowed_operations or DEFAULT_RESOURCE_OPERATIONS[resource_type]
        )
        if operation not in effective_operations:
            raise PermissionDeniedError(
                f"{resource_type} '{resource_id}' is not authorized for operation '{operation}'. "
                f"Allowed operations: {sorted(effective_operations)}"
            )

    def _validate_model_access(self, llm_model_uuid: str, operation: str) -> None:
        if llm_model_uuid not in self._allowed_model_ids:
            raise PermissionDeniedError(
                f"Model '{llm_model_uuid}' is not authorized. "
                f"Allowed models: {list(self._allowed_model_ids)}"
            )
        self._validate_operation(
            "model",
            llm_model_uuid,
            operation,
            self._allowed_model_operations.get(llm_model_uuid),
        )

    def _validate_tool_access(self, tool_name: str, operation: str) -> None:
        if tool_name not in self._allowed_tool_names:
            raise PermissionDeniedError(
                f"Tool '{tool_name}' is not authorized. "
                f"Allowed tools: {list(self._allowed_tool_names)}"
            )
        self._validate_operation(
            "tool",
            tool_name,
            operation,
            self._allowed_tool_operations.get(tool_name),
        )

    def _validate_knowledge_base_access(self, kb_id: str, operation: str) -> None:
        if kb_id not in self._allowed_kb_ids:
            raise PermissionDeniedError(
                f"Knowledge base '{kb_id}' is not authorized. "
                f"Allowed knowledge bases: {list(self._allowed_kb_ids)}"
            )
        self._validate_operation(
            "knowledge_base",
            kb_id,
            operation,
            self._allowed_kb_operations.get(kb_id),
        )

    def _validate_plugin_storage_access(self) -> None:
        if not self.ctx.resources.storage.plugin_storage:
            raise PermissionDeniedError("Plugin storage is not authorized.")

    def _validate_workspace_storage_access(self) -> None:
        if not self.ctx.resources.storage.workspace_storage:
            raise PermissionDeniedError("Workspace storage is not authorized.")

    # ================= LLM APIs (delegated with validation) =================

    async def invoke_llm(
        self,
        llm_model_uuid: str,
        messages: list[provider_message.Message],
        funcs: list[resource_tool.LLMTool] | None = None,
        extra_args: dict[str, Any] | None = None,
        timeout: float | None = None,
        remove_think: bool | None = None,
    ) -> provider_message.Message:
        """Invoke an LLM model with permission validation."""
        result = await self.invoke_llm_with_usage(
            llm_model_uuid=llm_model_uuid,
            messages=messages,
            funcs=funcs,
            extra_args=extra_args,
            timeout=timeout,
            remove_think=remove_think,
        )
        return result.message

    async def invoke_llm_with_usage(
        self,
        llm_model_uuid: str,
        messages: list[provider_message.Message],
        funcs: list[resource_tool.LLMTool] | None = None,
        extra_args: dict[str, Any] | None = None,
        timeout: float | None = None,
        remove_think: bool | None = None,
    ) -> provider_message.LLMInvokeResult:
        """Invoke an LLM model and return the message plus optional provider usage."""
        self._validate_model_access(llm_model_uuid, "invoke")
        effective_timeout = self._bounded_timeout(default=120.0, requested=timeout)
        funcs = funcs or []
        extra_args = extra_args or {}
        payload = {
            "run_id": self.run_id,
            "llm_model_uuid": llm_model_uuid,
            "messages": [m.model_dump() for m in messages],
            "funcs": [f.model_dump() for f in funcs],
            "extra_args": extra_args,
            "timeout": effective_timeout,
        }
        if remove_think is not None:
            payload["remove_think"] = remove_think
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.INVOKE_LLM,
            payload,
            effective_timeout,
        )
        return provider_message.LLMInvokeResult.model_validate(
            {
                "message": self._expect_key(
                    resp,
                    "message",
                    PluginToRuntimeAction.INVOKE_LLM,
                ),
                "usage": resp.get("usage") if isinstance(resp, dict) else None,
            }
        )

    async def invoke_llm_stream(
        self,
        llm_model_uuid: str,
        messages: list[provider_message.Message],
        funcs: list[resource_tool.LLMTool] | None = None,
        extra_args: dict[str, Any] | None = None,
        remove_think: bool | None = None,
    ):
        """Invoke an LLM model with streaming, permission validation."""
        async for event in self.invoke_llm_stream_events(
            llm_model_uuid=llm_model_uuid,
            messages=messages,
            funcs=funcs,
            extra_args=extra_args,
            remove_think=remove_think,
        ):
            if event.chunk is not None:
                yield event.chunk

    async def invoke_llm_stream_events(
        self,
        llm_model_uuid: str,
        messages: list[provider_message.Message],
        funcs: list[resource_tool.LLMTool] | None = None,
        extra_args: dict[str, Any] | None = None,
        remove_think: bool | None = None,
    ):
        """Invoke an LLM model and yield chunks plus optional final usage events."""
        self._validate_model_access(llm_model_uuid, "stream")
        effective_timeout = self._bounded_timeout(default=120.0)
        funcs = funcs or []
        extra_args = extra_args or {}
        payload = {
            "run_id": self.run_id,
            "llm_model_uuid": llm_model_uuid,
            "messages": [m.model_dump() for m in messages],
            "funcs": [f.model_dump() for f in funcs],
            "extra_args": extra_args,
            "timeout": effective_timeout,
        }
        if remove_think is not None:
            payload["remove_think"] = remove_think
        async for chunk_data in self._api.plugin_runtime_handler.call_action_generator(
            PluginToRuntimeAction.INVOKE_LLM_STREAM,
            payload,
            effective_timeout,
        ):
            event_data: dict[str, Any] = {}
            if isinstance(chunk_data, dict) and "chunk" in chunk_data:
                event_data["chunk"] = chunk_data["chunk"]
            if isinstance(chunk_data, dict) and "usage" in chunk_data:
                event_data["usage"] = chunk_data["usage"]
            if not event_data:
                event_data["chunk"] = self._expect_key(
                    chunk_data,
                    "chunk",
                    PluginToRuntimeAction.INVOKE_LLM_STREAM,
                )
            yield provider_message.LLMStreamEvent.model_validate(event_data)

    # ================= Tool APIs (delegated with validation) =================

    async def get_tool_detail(self, tool_name: str) -> dict[str, Any]:
        """Get tool detail with permission validation.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool detail dict containing:
            - name: Tool name
            - description: Tool description for LLM
            - parameters: JSON schema of parameters

        Raises:
            PermissionDeniedError: Tool not authorized for this run
        """
        self._validate_tool_access(tool_name, "detail")
        timeout = self._bounded_timeout(default=30.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_TOOL_DETAIL,
            {
                "run_id": self.run_id,
                "tool_name": tool_name,
            },
            timeout,
        )
        return self._expect_key(resp, "tool", PluginToRuntimeAction.GET_TOOL_DETAIL)

    async def call_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Call a tool with permission validation."""
        self._validate_tool_access(tool_name, "call")
        timeout = self._bounded_timeout(default=180.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.CALL_TOOL,
            {
                "run_id": self.run_id,
                "tool_name": tool_name,
                "parameters": parameters,
            },
            timeout,
        )
        return self._expect_key(resp, "result", PluginToRuntimeAction.CALL_TOOL)

    # ================= Knowledge Base API (delegated with validation) =================

    async def retrieve_knowledge(
        self,
        kb_id: str,
        query_text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve from knowledge base with permission validation."""
        self._validate_knowledge_base_access(kb_id, "retrieve")
        timeout = self._bounded_timeout(default=30.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE,
            {
                "run_id": self.run_id,
                "kb_id": kb_id,
                "query_text": query_text,
                "top_k": top_k,
                "filters": filters or {},
            },
            timeout,
        )
        return self._expect_key(
            resp,
            "results",
            PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE,
        )

    # ================= Storage APIs (delegated with validation) =================

    async def set_plugin_storage(self, key: str, value: bytes) -> None:
        """Set a plugin storage value with permission validation."""
        self._validate_plugin_storage_access()
        await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.SET_PLUGIN_STORAGE,
            {
                "run_id": self.run_id,
                "key": key,
                "value_base64": base64.b64encode(value).decode("utf-8"),
            },
            self._bounded_timeout(default=15.0),
        )

    async def get_plugin_storage(self, key: str) -> bytes:
        """Get a plugin storage value with permission validation."""
        self._validate_plugin_storage_access()
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_PLUGIN_STORAGE,
            {
                "run_id": self.run_id,
                "key": key,
            },
            self._bounded_timeout(default=15.0),
        )
        encoded = self._expect_key(
            resp,
            "value_base64",
            PluginToRuntimeAction.GET_PLUGIN_STORAGE,
        )
        return base64.b64decode(encoded)

    async def get_plugin_storage_keys(self) -> list[str]:
        """Get all plugin storage keys with permission validation."""
        self._validate_plugin_storage_access()
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_PLUGIN_STORAGE_KEYS,
            {
                "run_id": self.run_id,
            },
            self._bounded_timeout(default=15.0),
        )
        return self._expect_key(
            resp,
            "keys",
            PluginToRuntimeAction.GET_PLUGIN_STORAGE_KEYS,
        )

    async def delete_plugin_storage(self, key: str) -> None:
        """Delete a plugin storage value with permission validation."""
        self._validate_plugin_storage_access()
        await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.DELETE_PLUGIN_STORAGE,
            {
                "run_id": self.run_id,
                "key": key,
            },
            self._bounded_timeout(default=15.0),
        )

    async def set_workspace_storage(self, key: str, value: bytes) -> None:
        """Set a workspace storage value with permission validation."""
        self._validate_workspace_storage_access()
        await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.SET_WORKSPACE_STORAGE,
            {
                "run_id": self.run_id,
                "key": key,
                "value_base64": base64.b64encode(value).decode("utf-8"),
            },
            self._bounded_timeout(default=15.0),
        )

    async def get_workspace_storage(self, key: str) -> bytes:
        """Get a workspace storage value with permission validation."""
        self._validate_workspace_storage_access()
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_WORKSPACE_STORAGE,
            {
                "run_id": self.run_id,
                "key": key,
            },
            self._bounded_timeout(default=15.0),
        )
        encoded = self._expect_key(
            resp,
            "value_base64",
            PluginToRuntimeAction.GET_WORKSPACE_STORAGE,
        )
        return base64.b64decode(encoded)

    async def get_workspace_storage_keys(self) -> list[str]:
        """Get all workspace storage keys with permission validation."""
        self._validate_workspace_storage_access()
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_WORKSPACE_STORAGE_KEYS,
            {
                "run_id": self.run_id,
            },
            self._bounded_timeout(default=15.0),
        )
        return self._expect_key(
            resp,
            "keys",
            PluginToRuntimeAction.GET_WORKSPACE_STORAGE_KEYS,
        )

    async def delete_workspace_storage(self, key: str) -> None:
        """Delete a workspace storage value with permission validation."""
        self._validate_workspace_storage_access()
        await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.DELETE_WORKSPACE_STORAGE,
            {
                "run_id": self.run_id,
                "key": key,
            },
            self._bounded_timeout(default=15.0),
        )

    # ================= Version API (no authorization needed, delegated) =================

    async def get_langbot_version(self) -> str:
        """Get the LangBot version (no authorization needed)."""
        return await self._api.get_langbot_version()

    # ================= Rerank API (AgentRunner-specific, not in LangBotAPIProxy) =================

    async def invoke_rerank(
        self,
        rerank_model_uuid: str,
        query: str,
        documents: list[str],
        top_k: int | None = None,
        extra_args: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> list[dict[str, Any]]:
        """Invoke a rerank model to re-score documents.

        Args:
            rerank_model_uuid: UUID of the rerank model
            query: The query text for reranking
            documents: List of document texts to rerank
            top_k: Optional number of top results to return
            extra_args: Optional provider-specific options
            timeout: Request timeout in seconds

        Returns:
            List of dicts with 'index' and 'relevance_score' keys,
            sorted by relevance_score descending

        Example:
            results = await api.invoke_rerank(
                rerank_model_uuid="xxx-xxx",
                query="What is machine learning?",
                documents=["Doc 1 text", "Doc 2 text", "Doc 3 text"],
                top_k=5,
            )
            # results = [
            #     {"index": 2, "relevance_score": 0.95},
            #     {"index": 0, "relevance_score": 0.82},
            #     ...
            # ]
        """
        self._validate_model_access(rerank_model_uuid, "rerank")
        effective_timeout = self._bounded_timeout(default=30.0, requested=timeout)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.INVOKE_RERANK,
            {
                "run_id": self.run_id,
                "rerank_model_uuid": rerank_model_uuid,
                "query": query,
                "documents": documents,
                "top_k": top_k,
                "extra_args": extra_args or {},
            },
            timeout=effective_timeout,
        )
        return self._expect_key(resp, "results", PluginToRuntimeAction.INVOKE_RERANK)

    # ================= History APIs (run-scoped, conversation-scoped) =================

    async def get_prompt(self) -> list[dict[str, Any]]:
        """Get the Host effective prompt for the current run.

        The returned prompt reflects host-side PromptPreProcessing output for
        query-backed runs. Runners should fall back to ctx.config.prompt when
        this API is unavailable or returns an empty list.
        """
        self._require_context_api("prompt_get")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_PROMPT,
            {
                "run_id": self.run_id,
            },
            timeout,
        )
        prompt = self._expect_key(resp, "prompt", PluginToRuntimeAction.GET_PROMPT)
        if not isinstance(prompt, list):
            raise AgentAPIException(
                AgentAPIError(
                    code="host.malformed_response",
                    message=f"{PluginToRuntimeAction.GET_PROMPT.value} response field prompt must be a list",
                    retryable=False,
                    details={
                        "action": PluginToRuntimeAction.GET_PROMPT.value,
                        "field": "prompt",
                    },
                )
            )
        return prompt

    async def history_page(
        self,
        conversation_id: str | None = None,
        before_cursor: str | None = None,
        after_cursor: str | None = None,
        limit: int = 50,
        direction: str = "backward",
        include_attachments: bool = False,
    ) -> dict[str, Any]:
        """Page through transcript history for a conversation.

        Args:
            conversation_id: Conversation ID to query. Must match current run's
                conversation. If None, uses current run's conversation.
            before_cursor: Get items before this cursor (backward direction).
            after_cursor: Get items after this cursor (forward direction).
            limit: Maximum items to return. Has a hard cap on host side.
            direction: 'backward' (older items) or 'forward' (newer items).
            include_attachments: Whether to include attachment refs in items.

        Returns:
            HistoryPage with items, next_cursor, prev_cursor, has_more.

        Raises:
            PermissionDeniedError: If not authorized for this conversation.
        """
        self._require_context_api("history_page")
        timeout = self._bounded_timeout(default=30.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.HISTORY_PAGE,
            {
                "run_id": self.run_id,
                "conversation_id": conversation_id,
                "before_cursor": before_cursor,
                "after_cursor": after_cursor,
                "limit": limit,
                "direction": direction,
                "include_attachments": include_attachments,
            },
            timeout,
        )
        return HistoryPage.model_validate(resp)

    async def history_search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> HistorySearchResult:
        """Search transcript history for matching items.

        This is a basic search capability. Host implementation may use
        simple LIKE filtering initially.

        Args:
            query: Search query string.
            filters: Optional filters (conversation_id, event_types, etc.).
            top_k: Maximum results to return.

        Returns:
            HistorySearchResult with items, total_count, query.

        Note:
            Basic implementation may return unsupported error or limited results.
        """
        self._require_context_api("history_search")
        timeout = self._bounded_timeout(default=30.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.HISTORY_SEARCH,
            {
                "run_id": self.run_id,
                "query": query,
                "filters": filters or {},
                "top_k": top_k,
            },
            timeout,
        )
        return HistorySearchResult.model_validate(resp)

    # ================= Event APIs (run-scoped) =================

    async def event_get(self, event_id: str) -> AgentEventRecord:
        """Get a single event record by ID.

        Args:
            event_id: The event ID to retrieve.

        Returns:
            AgentEventRecord.

        Raises:
            PermissionDeniedError: If event not accessible by current run.
        """
        self._require_context_api("event_get")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.EVENT_GET,
            {
                "run_id": self.run_id,
                "event_id": event_id,
            },
            timeout,
        )
        return AgentEventRecord.model_validate(resp)

    async def event_page(
        self,
        conversation_id: str | None = None,
        event_types: list[str] | None = None,
        before_cursor: str | None = None,
        limit: int = 50,
    ) -> EventPage:
        """Page through event records.

        Args:
            conversation_id: Conversation ID to query. Must match current run.
            event_types: Filter by event types if specified.
            before_cursor: Get items before this cursor.
            limit: Maximum items to return. Has a hard cap on host side.

        Returns:
            EventPage with items, next_cursor, prev_cursor, has_more.

        Raises:
            PermissionDeniedError: If not authorized for this conversation.
        """
        self._require_context_api("event_page")
        timeout = self._bounded_timeout(default=30.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.EVENT_PAGE,
            {
                "run_id": self.run_id,
                "conversation_id": conversation_id,
                "event_types": event_types,
                "before_cursor": before_cursor,
                "limit": limit,
            },
            timeout,
        )
        return EventPage.model_validate(resp)

    # ================= Run Ledger APIs (run-scoped) =================

    async def run_get(self, run_id: str | None = None) -> AgentRun:
        """Get one Host-owned run record.

        Args:
            run_id: Run ID to retrieve. Defaults to the current run.

        Returns:
            AgentRun record.

        Raises:
            PermissionDeniedError: If run_get is not available.
        """
        self._require_context_api("run_get")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_GET,
            {
                "run_id": self.run_id,
                "target_run_id": run_id or self.run_id,
            },
            timeout,
        )
        return AgentRun.model_validate(resp)

    async def run_list(
        self,
        conversation_id: str | None = None,
        statuses: list[str] | None = None,
        before_cursor: str | None = None,
        limit: int = 50,
    ) -> RunPage:
        """List Host-owned run records visible to the current run scope.

        Args:
            conversation_id: Conversation ID to query. Must match current run
                scope if supplied.
            statuses: Optional run status filter.
            before_cursor: Cursor returned by a previous page.
            limit: Maximum items to return. Host applies a hard cap.
        """
        self._require_context_api("run_list")
        timeout = self._bounded_timeout(default=30.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_LIST,
            {
                "run_id": self.run_id,
                "conversation_id": conversation_id,
                "statuses": statuses,
                "before_cursor": before_cursor,
                "limit": limit,
            },
            timeout,
        )
        return RunPage.model_validate(resp)

    async def run_events_page(
        self,
        run_id: str | None = None,
        before_cursor: str | None = None,
        after_cursor: str | None = None,
        limit: int = 50,
        direction: str = "forward",
    ) -> RunEventPage:
        """Page through result events for one Host-owned run.

        Args:
            run_id: Run ID to inspect. Defaults to the current run.
            before_cursor: Get events before this sequence.
            after_cursor: Get events after this sequence.
            limit: Maximum items to return. Host applies a hard cap.
            direction: "forward" or "backward".
        """
        self._require_context_api("run_events_page")
        timeout = self._bounded_timeout(default=30.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_EVENTS_PAGE,
            {
                "run_id": self.run_id,
                "target_run_id": run_id or self.run_id,
                "before_cursor": before_cursor,
                "after_cursor": after_cursor,
                "limit": limit,
                "direction": direction,
            },
            timeout,
        )
        return RunEventPage.model_validate(resp)

    async def run_cancel(
        self,
        run_id: str | None = None,
        reason: str | None = None,
    ) -> AgentRun:
        """Request cancellation for one Host-owned run.

        Args:
            run_id: Run ID to cancel. Defaults to the current run.
            reason: Optional cancellation reason for Host audit/debug output.
        """
        self._require_context_api("run_cancel")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_CANCEL,
            {
                "run_id": self.run_id,
                "target_run_id": run_id or self.run_id,
                "reason": reason,
            },
            timeout,
        )
        return AgentRun.model_validate(resp)

    async def run_append_result(
        self,
        result: AgentRunResult,
    ) -> AgentRunEvent:
        """Append one result event to a Host-owned run ledger.

        Args:
            result: Existing AgentRunResult DTO to persist.
        """
        self._require_context_api("run_append_result")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_APPEND_RESULT,
            {
                "run_id": self.run_id,
                "target_run_id": result.run_id,
                "result": result.model_dump(mode="json"),
            },
            timeout,
        )
        return AgentRunEvent.model_validate(resp)

    async def run_finalize(
        self,
        run_id: str | None = None,
        status: str | None = None,
        reason: str | None = None,
    ) -> AgentRun:
        """Finalize one Host-owned run ledger record.

        Args:
            run_id: Run ID to finalize. Defaults to the current run.
            status: Optional terminal status supplied by the caller.
            reason: Optional terminal status reason for Host audit/debug output.
        """
        self._require_context_api("run_finalize")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_FINALIZE,
            {
                "run_id": self.run_id,
                "target_run_id": run_id or self.run_id,
                "status": status,
                "reason": reason,
            },
            timeout,
        )
        return AgentRun.model_validate(resp)

    # ================= Runtime Registry and Claim Lease APIs =================

    async def runtime_register(
        self,
        runtime_id: str,
        status: str = "online",
        display_name: str | None = None,
        endpoint: str | None = None,
        version: str | None = None,
        capabilities: dict[str, Any] | None = None,
        labels: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        heartbeat_deadline_at: int | None = None,
    ) -> AgentRuntime:
        """Register or update one Host-owned runtime record."""
        self._require_context_api("runtime_register")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUNTIME_REGISTER,
            {
                "run_id": self.run_id,
                "runtime_id": runtime_id,
                "status": status,
                "display_name": display_name,
                "endpoint": endpoint,
                "version": version,
                "capabilities": capabilities or {},
                "labels": labels or {},
                "metadata": metadata or {},
                "heartbeat_deadline_at": heartbeat_deadline_at,
            },
            timeout,
        )
        return AgentRuntime.model_validate(resp)

    async def runtime_heartbeat(
        self,
        runtime_id: str,
        status: str | None = None,
        capabilities: dict[str, Any] | None = None,
        labels: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        heartbeat_deadline_at: int | None = None,
    ) -> AgentRuntime:
        """Refresh one Host-owned runtime record heartbeat."""
        self._require_context_api("runtime_heartbeat")
        timeout = self._bounded_timeout(default=10.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUNTIME_HEARTBEAT,
            {
                "run_id": self.run_id,
                "runtime_id": runtime_id,
                "status": status,
                "capabilities": capabilities,
                "labels": labels,
                "metadata": metadata,
                "heartbeat_deadline_at": heartbeat_deadline_at,
            },
            timeout,
        )
        return AgentRuntime.model_validate(resp)

    async def runtime_list(
        self,
        statuses: list[str] | None = None,
        labels: dict[str, str] | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> RuntimePage:
        """List Host-owned runtime records visible to this API scope."""
        self._require_context_api("runtime_list")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUNTIME_LIST,
            {
                "run_id": self.run_id,
                "statuses": statuses,
                "labels": labels or {},
                "cursor": cursor,
                "limit": limit,
            },
            timeout,
        )
        return RuntimePage.model_validate(resp)

    async def run_claim(
        self,
        runtime_id: str,
        queue_name: str | None = None,
        lease_seconds: int = 60,
    ) -> AgentRun:
        """Claim one queued run for a runtime lease."""
        self._require_context_api("run_claim")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_CLAIM,
            {
                "run_id": self.run_id,
                "runtime_id": runtime_id,
                "queue_name": queue_name,
                "lease_seconds": lease_seconds,
            },
            timeout,
        )
        return AgentRun.model_validate(resp)

    async def run_renew_claim(
        self,
        run_id: str,
        runtime_id: str,
        claim_token: str,
        lease_seconds: int = 60,
    ) -> AgentRun:
        """Renew an existing run claim lease."""
        self._require_context_api("run_renew_claim")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_RENEW_CLAIM,
            {
                "run_id": self.run_id,
                "target_run_id": run_id,
                "runtime_id": runtime_id,
                "claim_token": claim_token,
                "lease_seconds": lease_seconds,
            },
            timeout,
        )
        return AgentRun.model_validate(resp)

    async def run_release_claim(
        self,
        run_id: str,
        runtime_id: str,
        claim_token: str,
        reason: str | None = None,
    ) -> AgentRun:
        """Release an existing run claim lease."""
        self._require_context_api("run_release_claim")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.RUN_RELEASE_CLAIM,
            {
                "run_id": self.run_id,
                "target_run_id": run_id,
                "runtime_id": runtime_id,
                "claim_token": claim_token,
                "reason": reason,
            },
            timeout,
        )
        return AgentRun.model_validate(resp)

    async def steering_pull(
        self,
        mode: str = "all",
        limit: int | None = None,
    ) -> SteeringPullResult:
        """Pull pending run-scoped steering/follow-up input.

        Args:
            mode: "all" to pull all currently queued items in Host claim order,
                or "one"/"one-at-a-time" to pull one item. Host does not merge
                multiple user messages.
            limit: Optional maximum number of items to pull. Host applies a
                hard cap.

        Returns:
            SteeringPullResult with items containing event/input/context
            projections for messages claimed by the active run.

        Raises:
            PermissionDeniedError: If steering_pull is not available.
        """
        self._require_context_api("steering_pull")
        timeout = self._bounded_timeout(default=10.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.STEERING_PULL,
            {
                "run_id": self.run_id,
                "mode": mode,
                "limit": limit,
            },
            timeout,
        )
        return SteeringPullResult.model_validate(resp)

    # ================= State APIs (run-scoped, policy-enforced) =================

    async def state_get(self, scope: str, key: str) -> dict[str, Any]:
        """Get a state value from host-owned state store.

        Args:
            scope: State scope ('conversation', 'actor', 'subject', 'runner').
            key: State key (should use namespace prefix like 'external.*').

        Returns:
            Dict with 'value' key containing the stored value, or 'value': None
            if key does not exist.

        Raises:
            PermissionDeniedError: If scope not enabled by state_policy.
        """
        self._require_context_api("state")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.STATE_GET,
            {
                "run_id": self.run_id,
                "scope": scope,
                "key": key,
            },
            timeout,
        )
        return resp

    async def state_set(self, scope: str, key: str, value: Any) -> dict[str, Any]:
        """Set a state value in host-owned state store.

        Args:
            scope: State scope ('conversation', 'actor', 'subject', 'runner').
            key: State key (should use namespace prefix like 'external.*').
            value: State value (must be JSON-serializable, size-limited).

        Returns:
            Dict with 'success' key.

        Raises:
            PermissionDeniedError: If scope not enabled by state_policy.
        """
        self._require_context_api("state")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.STATE_SET,
            {
                "run_id": self.run_id,
                "scope": scope,
                "key": key,
                "value": value,
            },
            timeout,
        )
        return resp

    async def state_delete(self, scope: str, key: str) -> dict[str, Any]:
        """Delete a state value from host-owned state store.

        Args:
            scope: State scope ('conversation', 'actor', 'subject', 'runner').
            key: State key to delete.

        Returns:
            Dict with 'success' key (True if deleted, False if not found).

        Raises:
            PermissionDeniedError: If scope not enabled by state_policy.
        """
        self._require_context_api("state")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.STATE_DELETE,
            {
                "run_id": self.run_id,
                "scope": scope,
                "key": key,
            },
            timeout,
        )
        return resp

    async def state_list(
        self,
        scope: str,
        prefix: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List state keys in a scope.

        Args:
            scope: State scope ('conversation', 'actor', 'subject', 'runner').
            prefix: Optional prefix to filter keys (e.g., 'external.').
            limit: Maximum number of keys to return (host-enforced cap of 100).

        Returns:
            Dict with 'keys' key containing list of key names, and 'has_more'
            boolean indicating if more keys are available.

        Raises:
            PermissionDeniedError: If scope not enabled by state_policy.
        """
        self._require_context_api("state")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.STATE_LIST,
            {
                "run_id": self.run_id,
                "scope": scope,
                "prefix": prefix,
                "limit": limit,
            },
            timeout,
        )
        return resp


class AgentRunAdminAPIProxy:
    """Admin API proxy for Host-authorized control plugins.

    This proxy is intended for plugin Page backends or runtime daemons that are
    explicitly granted Host-level permissions such as ``agent_run:admin`` or
    ``runtime:admin`` in LangBot config. It does not carry an AgentRunContext or
    run_id; Host action handlers remain the source of truth for authorization.
    """

    plugin_runtime_handler: Handler

    def __init__(self, plugin_runtime_handler: Handler):
        self.plugin_runtime_handler = plugin_runtime_handler

    async def _call_action(
        self,
        action: PluginToRuntimeAction,
        data: dict[str, Any],
        timeout: float,
    ) -> Any:
        try:
            return await self.plugin_runtime_handler.call_action(action, data, timeout)
        except ActionCallError as error:
            raise _build_agent_api_exception(action, error) from error
        except (ActionCallTimeoutError, ConnectionClosedError) as error:
            raise _build_transport_api_exception(action, error) from error

    async def run_get(self, run_id: str) -> AgentRun:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_GET,
            {"target_run_id": run_id},
            15.0,
        )
        return AgentRun.model_validate(resp)

    async def run_list(
        self,
        conversation_id: str | None = None,
        statuses: list[str] | None = None,
        before_cursor: str | None = None,
        limit: int = 50,
    ) -> RunPage:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_LIST,
            {
                "conversation_id": conversation_id,
                "statuses": statuses,
                "before_cursor": before_cursor,
                "limit": limit,
            },
            30.0,
        )
        return RunPage.model_validate(resp)

    async def run_events_page(
        self,
        run_id: str,
        before_cursor: str | None = None,
        after_cursor: str | None = None,
        limit: int = 50,
        direction: str = "forward",
    ) -> RunEventPage:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_EVENTS_PAGE,
            {
                "target_run_id": run_id,
                "before_cursor": before_cursor,
                "after_cursor": after_cursor,
                "limit": limit,
                "direction": direction,
            },
            30.0,
        )
        return RunEventPage.model_validate(resp)

    async def run_cancel(
        self,
        run_id: str,
        reason: str | None = None,
    ) -> AgentRun:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_CANCEL,
            {
                "target_run_id": run_id,
                "reason": reason,
            },
            15.0,
        )
        return AgentRun.model_validate(resp)

    async def run_append_result(
        self,
        result: AgentRunResult,
    ) -> AgentRunEvent:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_APPEND_RESULT,
            {
                "target_run_id": result.run_id,
                "result": result.model_dump(mode="json"),
            },
            15.0,
        )
        return AgentRunEvent.model_validate(resp)

    async def run_finalize(
        self,
        run_id: str,
        status: str,
        reason: str | None = None,
        usage: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRun:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_FINALIZE,
            {
                "target_run_id": run_id,
                "status": status,
                "reason": reason,
                "usage": usage,
                "cost": cost,
                "metadata": metadata,
            },
            15.0,
        )
        return AgentRun.model_validate(resp)

    async def runtime_register(
        self,
        runtime_id: str,
        status: str = "online",
        display_name: str | None = None,
        endpoint: str | None = None,
        version: str | None = None,
        capabilities: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        heartbeat_deadline_at: int | float | None = None,
    ) -> AgentRuntime:
        resp = await self._call_action(
            PluginToRuntimeAction.RUNTIME_REGISTER,
            {
                "runtime_id": runtime_id,
                "status": status,
                "display_name": display_name,
                "endpoint": endpoint,
                "version": version,
                "capabilities": capabilities or {},
                "labels": labels or {},
                "metadata": metadata or {},
                "heartbeat_deadline_at": heartbeat_deadline_at,
            },
            15.0,
        )
        return AgentRuntime.model_validate(resp)

    async def runtime_heartbeat(
        self,
        runtime_id: str,
        status: str = "online",
        capabilities: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        heartbeat_deadline_at: int | float | None = None,
    ) -> AgentRuntime:
        resp = await self._call_action(
            PluginToRuntimeAction.RUNTIME_HEARTBEAT,
            {
                "runtime_id": runtime_id,
                "status": status,
                "capabilities": capabilities,
                "labels": labels,
                "metadata": metadata,
                "heartbeat_deadline_at": heartbeat_deadline_at,
            },
            10.0,
        )
        return AgentRuntime.model_validate(resp)

    async def runtime_list(
        self,
        statuses: list[str] | None = None,
        labels: dict[str, str] | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> RuntimePage:
        resp = await self._call_action(
            PluginToRuntimeAction.RUNTIME_LIST,
            {
                "statuses": statuses,
                "labels": labels or {},
                "cursor": cursor,
                "limit": limit,
            },
            15.0,
        )
        return RuntimePage.model_validate(resp)

    async def runner_list(
        self,
        include_plugins: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        resp = await self._call_action(
            PluginToRuntimeAction.RUNNER_LIST,
            {
                "include_plugins": include_plugins,
            },
            15.0,
        )
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict) and isinstance(resp.get("items"), list):
            return resp["items"]
        raise AgentAPIException(
            AgentAPIError(
                code="host.malformed_response",
                message=(
                    f"{PluginToRuntimeAction.RUNNER_LIST.value} response must be "
                    "a list or contain an items list"
                ),
                retryable=False,
                details={"action": PluginToRuntimeAction.RUNNER_LIST.value},
            )
        )

    async def runtime_reconcile(
        self,
        stale_after_seconds: float | None = None,
    ) -> dict[str, Any]:
        resp = await self._call_action(
            PluginToRuntimeAction.RUNTIME_RECONCILE,
            {
                "stale_after_seconds": stale_after_seconds,
            },
            30.0,
        )
        if isinstance(resp, dict):
            return resp
        raise AgentAPIException(
            AgentAPIError(
                code="host.malformed_response",
                message=(
                    f"{PluginToRuntimeAction.RUNTIME_RECONCILE.value} response "
                    "must be a dict"
                ),
                retryable=False,
                details={"action": PluginToRuntimeAction.RUNTIME_RECONCILE.value},
            )
        )

    async def run_claim(
        self,
        runtime_id: str,
        queue_name: str | None = None,
        lease_seconds: int = 60,
        runner_ids: list[str] | None = None,
    ) -> AgentRun:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_CLAIM,
            {
                "runtime_id": runtime_id,
                "queue_name": queue_name,
                "lease_seconds": lease_seconds,
                "runner_ids": runner_ids,
            },
            15.0,
        )
        return AgentRun.model_validate(resp)

    async def run_renew_claim(
        self,
        run_id: str,
        runtime_id: str,
        claim_token: str,
        lease_seconds: int = 60,
    ) -> AgentRun:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_RENEW_CLAIM,
            {
                "target_run_id": run_id,
                "runtime_id": runtime_id,
                "claim_token": claim_token,
                "lease_seconds": lease_seconds,
            },
            15.0,
        )
        return AgentRun.model_validate(resp)

    async def run_release_claim(
        self,
        run_id: str,
        runtime_id: str,
        claim_token: str,
        reason: str | None = None,
    ) -> AgentRun:
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_RELEASE_CLAIM,
            {
                "target_run_id": run_id,
                "runtime_id": runtime_id,
                "claim_token": claim_token,
                "reason": reason,
            },
            15.0,
        )
        return AgentRun.model_validate(resp)

    async def run_stats(
        self,
        start_time: int | None = None,
        end_time: int | None = None,
        runner_id: str | None = None,
    ) -> RunStats:
        """Get run statistics within a time window.

        Args:
            start_time: Unix timestamp for start of window (optional, defaults to 1 hour ago)
            end_time: Unix timestamp for end of window (optional, defaults to now)
            runner_id: Filter by runner ID (optional)

        Returns:
            RunStats with counts, rates, and duration percentiles.
        """
        resp = await self._call_action(
            PluginToRuntimeAction.RUN_STATS,
            {
                "start_time": start_time,
                "end_time": end_time,
                "runner_id": runner_id,
            },
            30.0,
        )
        return RunStats.model_validate(resp)

    async def runtime_stats(self) -> RuntimeStats:
        """Get runtime registry statistics.

        Returns:
            RuntimeStats with counts, heartbeat health, and capacity.
        """
        resp = await self._call_action(
            PluginToRuntimeAction.RUNTIME_STATS,
            {},
            15.0,
        )
        return RuntimeStats.model_validate(resp)

    async def runner_stats(
        self,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 50,
    ) -> RunnerStatsPage:
        """Get runner-aggregated statistics.

        Args:
            start_time: Unix timestamp for start of window (optional, defaults to 1 hour ago)
            end_time: Unix timestamp for end of window (optional, defaults to now)
            limit: Maximum number of runners to return (default 50, max 100)

        Returns:
            RunnerStatsPage with per-runner statistics.
        """
        resp = await self._call_action(
            PluginToRuntimeAction.RUNNER_STATS,
            {
                "start_time": start_time,
                "end_time": end_time,
                "limit": limit,
            },
            30.0,
        )
        return RunnerStatsPage.model_validate(resp)
