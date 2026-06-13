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
from langbot_plugin.api.entities.builtin.agent_runner.artifact import (
    ArtifactMetadata,
    ArtifactReadResult,
)
from langbot_plugin.api.entities.builtin.agent_runner.page_results import (
    AgentEventRecord,
    EventPage,
    HistoryPage,
    HistorySearchResult,
)
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
    "file": frozenset({"config", "knowledge"}),
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
            async for item in self._handler.call_action_generator(action, data, timeout):
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
    - get_file(): requires file_id in ctx.resources.files

    Helper methods (local read from ctx.resources):
    - get_allowed_models(): returns ctx.resources.models
    - get_allowed_tools(): returns ctx.resources.tools
    - get_allowed_knowledge_bases(): returns ctx.resources.knowledge_bases
    - get_allowed_files(): returns ctx.resources.files

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
    _allowed_file_ids: frozenset[str]
    _allowed_model_operations: dict[str, frozenset[str]]
    _allowed_tool_operations: dict[str, frozenset[str]]
    _allowed_kb_operations: dict[str, frozenset[str]]
    _allowed_file_operations: dict[str, frozenset[str]]

    def __init__(self, ctx: AgentRunContext, plugin_runtime_handler: Handler):
        self.ctx = ctx
        self._api = LangBotAPIProxy(_AgentRunHandlerAdapter(plugin_runtime_handler))
        # Pre-compute allowed IDs for efficient validation
        self._allowed_model_ids = frozenset(m.model_id for m in ctx.resources.models)
        self._allowed_tool_names = frozenset(t.tool_name for t in ctx.resources.tools)
        self._allowed_kb_ids = frozenset(k.kb_id for k in ctx.resources.knowledge_bases)
        self._allowed_file_ids = frozenset(f.file_id for f in ctx.resources.files)
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
        self._allowed_file_operations = {
            f.file_id: self._normalize_operations("file", f.operations)
            for f in ctx.resources.files
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

    def get_allowed_files(self) -> list[Any]:
        """Get the list of files authorized for this run."""
        return self.ctx.resources.files

    # ================= Permission Validation =================

    @staticmethod
    def _normalize_operations(resource_type: str, operations: list[str] | None) -> frozenset[str]:
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
        effective_operations = allowed_operations or DEFAULT_RESOURCE_OPERATIONS[resource_type]
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

    def _validate_file_access(self, file_key: str, operation: str) -> None:
        if file_key not in self._allowed_file_ids:
            raise PermissionDeniedError(
                f"File '{file_key}' is not authorized. "
                f"Allowed files: {list(self._allowed_file_ids)}"
            )
        self._validate_operation(
            "file",
            file_key,
            operation,
            self._allowed_file_operations.get(file_key),
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

    # ================= File API (delegated with validation) =================

    async def get_file(self, file_key: str) -> bytes:
        """Get a file with permission validation.

        Args:
            file_key: The file key from ctx.resources.files

        Returns:
            The file content as bytes
        """
        self._validate_file_access(file_key, "config")
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_CONFIG_FILE,
            {
                "run_id": self.run_id,
                "file_key": file_key,
            },
            self._bounded_timeout(default=15.0),
        )
        encoded = self._expect_key(
            resp,
            "file_base64",
            PluginToRuntimeAction.GET_CONFIG_FILE,
        )
        return base64.b64decode(encoded)

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
        return resp.get("results", [])

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
        prompt = resp.get("prompt", [])
        return prompt if isinstance(prompt, list) else []

    async def history_page(
        self,
        conversation_id: str | None = None,
        before_cursor: str | None = None,
        after_cursor: str | None = None,
        limit: int = 50,
        direction: str = "backward",
        include_artifacts: bool = False,
    ) -> dict[str, Any]:
        """Page through transcript history for a conversation.

        Args:
            conversation_id: Conversation ID to query. Must match current run's
                conversation. If None, uses current run's conversation.
            before_cursor: Get items before this cursor (backward direction).
            after_cursor: Get items after this cursor (forward direction).
            limit: Maximum items to return. Has a hard cap on host side.
            direction: 'backward' (older items) or 'forward' (newer items).
            include_artifacts: Whether to include artifact refs in items.

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
                "include_artifacts": include_artifacts,
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

    # ================= Artifact APIs (run-scoped) =================

    async def artifact_metadata(self, artifact_id: str) -> ArtifactMetadata:
        """Get metadata for an artifact.

        Args:
            artifact_id: The artifact ID to retrieve metadata for.

        Returns:
            ArtifactMetadata with artifact_id, artifact_type, mime_type,
            size_bytes, source, conversation_id, run_id, etc.

        Raises:
            PermissionDeniedError: If artifact not accessible by current run.
        """
        self._require_context_api("artifact_metadata")
        timeout = self._bounded_timeout(default=15.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.ARTIFACT_METADATA,
            {
                "run_id": self.run_id,
                "artifact_id": artifact_id,
            },
            timeout,
        )
        return ArtifactMetadata.model_validate(resp)

    async def artifact_read(
        self,
        artifact_id: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> ArtifactReadResult:
        """Read artifact content.

        For small artifacts, returns content_base64 directly.
        For large artifacts, may return file_key for chunked transfer.

        Args:
            artifact_id: The artifact ID to read.
            offset: Byte offset to start reading from (for range reads).
            limit: Maximum bytes to read. Host may enforce a hard limit.

        Returns:
            ArtifactReadResult with:
            - artifact_id: The artifact identifier
            - mime_type: MIME type of content
            - size_bytes: Total artifact size
            - offset: Offset of this read
            - length: Length of data read (or None for file_key mode)
            - content_base64: Base64-encoded content (for inline mode)
            - file_key: File key for chunked transfer (for large artifacts)
            - has_more: Whether more data is available

        Raises:
            PermissionDeniedError: If artifact not accessible by current run.

        Note:
            Host may enforce max read size limits to prevent memory exhaustion.
            For large artifacts, prefer using file_key and chunked transfer.
        """
        self._require_context_api("artifact_read")
        timeout = self._bounded_timeout(default=60.0)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.ARTIFACT_READ,
            {
                "run_id": self.run_id,
                "artifact_id": artifact_id,
                "offset": offset,
                "limit": limit,
            },
            timeout,
        )
        return ArtifactReadResult.model_validate(resp)

    # Alias for artifact_read with range semantics
    async def artifact_read_range(
        self,
        artifact_id: str,
        offset: int = 0,
        length: int | None = None,
    ) -> ArtifactReadResult:
        """Read a range of artifact content.

        Alias for artifact_read with clearer range semantics.

        Args:
            artifact_id: The artifact ID to read.
            offset: Byte offset to start reading from.
            length: Maximum bytes to read.

        Returns:
            ArtifactReadResult.
        """
        return await self.artifact_read(artifact_id, offset=offset, limit=length)

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
