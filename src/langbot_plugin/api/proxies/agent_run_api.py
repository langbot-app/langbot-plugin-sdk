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
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.api.entities.builtin.provider import message as provider_message
from langbot_plugin.api.entities.builtin.resource import tool as resource_tool
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.proxies.langbot_api import LangBotAPIProxy


class PermissionDeniedError(Exception):
    """Raised when an API call is not authorized by ctx.resources."""

    pass


class AgentRunAPIProxy:
    """Restricted API proxy for AgentRunner execution.

    Uses COMPOSITION + DELEGATION to LangBotAPIProxy:
    - Validates permissions before delegating calls
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

    def __init__(self, ctx: AgentRunContext, plugin_runtime_handler: Handler):
        self.ctx = ctx
        self._api = LangBotAPIProxy(plugin_runtime_handler)
        # Pre-compute allowed IDs for efficient validation
        self._allowed_model_ids = frozenset(m.model_id for m in ctx.resources.models)
        self._allowed_tool_names = frozenset(t.tool_name for t in ctx.resources.tools)
        self._allowed_kb_ids = frozenset(k.kb_id for k in ctx.resources.knowledge_bases)
        self._allowed_file_ids = frozenset(f.file_id for f in ctx.resources.files)

    @property
    def run_id(self) -> str:
        """Unique identifier for this agent run."""
        return self.ctx.run_id

    @property
    def query_id(self) -> int:
        """Query ID from runtime context (for legacy compatibility)."""
        return self.ctx.runtime.query_id or 0

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

    def _validate_model_access(self, llm_model_uuid: str) -> None:
        if llm_model_uuid not in self._allowed_model_ids:
            raise PermissionDeniedError(
                f"Model '{llm_model_uuid}' is not authorized. "
                f"Allowed models: {list(self._allowed_model_ids)}"
            )

    def _validate_tool_access(self, tool_name: str) -> None:
        if tool_name not in self._allowed_tool_names:
            raise PermissionDeniedError(
                f"Tool '{tool_name}' is not authorized. "
                f"Allowed tools: {list(self._allowed_tool_names)}"
            )

    def _validate_knowledge_base_access(self, kb_id: str) -> None:
        if kb_id not in self._allowed_kb_ids:
            raise PermissionDeniedError(
                f"Knowledge base '{kb_id}' is not authorized. "
                f"Allowed knowledge bases: {list(self._allowed_kb_ids)}"
            )

    def _validate_file_access(self, file_key: str) -> None:
        if file_key not in self._allowed_file_ids:
            raise PermissionDeniedError(
                f"File '{file_key}' is not authorized. "
                f"Allowed files: {list(self._allowed_file_ids)}"
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
        funcs: list[resource_tool.LLMTool] = [],
        extra_args: dict[str, Any] = {},
        timeout: float | None = None,
        remove_think: bool | None = None,
    ) -> provider_message.Message:
        """Invoke an LLM model with permission validation."""
        self._validate_model_access(llm_model_uuid)
        effective_timeout = timeout if timeout is not None else 120.0
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
        return provider_message.Message.model_validate(resp["message"])

    async def invoke_llm_stream(
        self,
        llm_model_uuid: str,
        messages: list[provider_message.Message],
        funcs: list[resource_tool.LLMTool] = [],
        extra_args: dict[str, Any] = {},
        remove_think: bool | None = None,
    ):
        """Invoke an LLM model with streaming, permission validation."""
        self._validate_model_access(llm_model_uuid)
        payload = {
            "run_id": self.run_id,
            "llm_model_uuid": llm_model_uuid,
            "messages": [m.model_dump() for m in messages],
            "funcs": [f.model_dump() for f in funcs],
            "extra_args": extra_args,
            "timeout": 120.0,
        }
        if remove_think is not None:
            payload["remove_think"] = remove_think
        async for chunk_data in self._api.plugin_runtime_handler.call_action_generator(
            PluginToRuntimeAction.INVOKE_LLM_STREAM,
            payload,
            120.0,
        ):
            yield provider_message.MessageChunk.model_validate(chunk_data["chunk"])

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
        self._validate_tool_access(tool_name)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_TOOL_DETAIL,
            {
                "run_id": self.run_id,
                "tool_name": tool_name,
            },
            30,
        )
        return resp.get("tool", resp)

    async def call_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a tool with permission validation.

        Note: Simplified signature without session/query_id (obtained from ctx).
        Returns 'result' key instead of 'tool_response'.
        """
        self._validate_tool_access(tool_name)
        resp = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.CALL_TOOL,
            {
                "run_id": self.run_id,
                "tool_name": tool_name,
                "parameters": parameters,
                "session": session or {},
                "query_id": self.query_id,
            },
            180,
        )
        return resp.get("result", resp.get("tool_response", resp))

    # ================= Knowledge Base API (delegated with validation) =================

    async def retrieve_knowledge(
        self,
        kb_id: str,
        query_text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve from knowledge base with permission validation."""
        self._validate_knowledge_base_access(kb_id)
        return (
            await self._api.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE,
                {
                    "run_id": self.run_id,
                    "query_id": self.query_id,
                    "kb_id": kb_id,
                    "query_text": query_text,
                    "top_k": top_k,
                    "filters": filters or {},
                },
                30,
            )
        )["results"]

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
        )

    async def get_plugin_storage(self, key: str) -> bytes:
        """Get a plugin storage value with permission validation."""
        self._validate_plugin_storage_access()
        resp = (
            await self._api.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_PLUGIN_STORAGE,
                {
                    "run_id": self.run_id,
                    "key": key,
                },
            )
        )["value_base64"]
        return base64.b64decode(resp)

    async def get_plugin_storage_keys(self) -> list[str]:
        """Get all plugin storage keys with permission validation."""
        self._validate_plugin_storage_access()
        return (
            await self._api.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_PLUGIN_STORAGE_KEYS,
                {
                    "run_id": self.run_id,
                },
            )
        )["keys"]

    async def delete_plugin_storage(self, key: str) -> None:
        """Delete a plugin storage value with permission validation."""
        self._validate_plugin_storage_access()
        await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.DELETE_PLUGIN_STORAGE,
            {
                "run_id": self.run_id,
                "key": key,
            },
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
        )

    async def get_workspace_storage(self, key: str) -> bytes:
        """Get a workspace storage value with permission validation."""
        self._validate_workspace_storage_access()
        resp = (
            await self._api.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_WORKSPACE_STORAGE,
                {
                    "run_id": self.run_id,
                    "key": key,
                },
            )
        )["value_base64"]
        return base64.b64decode(resp)

    async def get_workspace_storage_keys(self) -> list[str]:
        """Get all workspace storage keys with permission validation."""
        self._validate_workspace_storage_access()
        return (
            await self._api.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_WORKSPACE_STORAGE_KEYS,
                {
                    "run_id": self.run_id,
                },
            )
        )["keys"]

    async def delete_workspace_storage(self, key: str) -> None:
        """Delete a workspace storage value with permission validation."""
        self._validate_workspace_storage_access()
        await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.DELETE_WORKSPACE_STORAGE,
            {
                "run_id": self.run_id,
                "key": key,
            },
        )

    # ================= File API (delegated with validation) =================

    async def get_file(self, file_key: str) -> bytes:
        """Get a file with permission validation.

        Args:
            file_key: The file key from ctx.resources.files

        Returns:
            The file content as bytes
        """
        self._validate_file_access(file_key)
        resp = (
            await self._api.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_CONFIG_FILE,
                {
                    "run_id": self.run_id,
                    "file_key": file_key,
                },
            )
        )["file_base64"]
        return base64.b64decode(resp)

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
        self._validate_model_access(rerank_model_uuid)
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
            timeout=timeout,
        )
        return resp.get("results", [])
