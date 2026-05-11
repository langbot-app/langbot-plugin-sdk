"""AgentRun API Proxy for AgentRunner components.

This proxy provides a restricted API for AgentRunner execution,
with all capabilities explicitly authorized through ctx.resources.
"""

from __future__ import annotations

from typing import Any

from langbot_plugin.runtime.io.handler import Handler
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.api.proxies.langbot_api import LangBotAPIProxy
from langbot_plugin.api.entities.builtin.provider import message as provider_message
from langbot_plugin.api.entities.builtin.resource import tool as resource_tool
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext


class PermissionDeniedError(Exception):
    """Raised when an API call is not authorized by ctx.resources."""

    pass


class AgentRunAPIProxy(LangBotAPIProxy):
    """Restricted API proxy for AgentRunner execution.

    Inherits from LangBotAPIProxy and adds permission validation.
    All resource access is validated against AgentRunContext.resources.

    Authorized APIs (validated against ctx.resources):
    - invoke_llm() / invoke_llm_stream(): requires model in ctx.resources.models
    - call_tool(): requires tool_name in ctx.resources.tools
    - retrieve_knowledge(): requires kb_id in ctx.resources.knowledge_bases
    - plugin_storage: requires ctx.resources.storage.plugin_storage=True
    - workspace_storage: requires ctx.resources.storage.workspace_storage=True
    - get_file(): requires file_id in ctx.resources.files

    Helper methods (local read from ctx.resources):
    - get_allowed_models(): returns ctx.resources.models
    - get_allowed_tools(): returns ctx.resources.tools
    - get_allowed_knowledge_bases(): returns ctx.resources.knowledge_bases
    - get_allowed_files(): returns ctx.resources.files

    Not available (platform actions, use AgentRunResult.action_requested instead):
    - get_bots() / get_bot_info() / send_message()
    """

    ctx: AgentRunContext
    """Agent run context containing run_id, resources, and runtime info."""

    # Pre-computed allowed IDs for efficient O(1) validation
    _allowed_model_ids: frozenset[str]
    _allowed_tool_names: frozenset[str]
    _allowed_kb_ids: frozenset[str]
    _allowed_file_ids: frozenset[str]

    def __init__(self, ctx: AgentRunContext, plugin_runtime_handler: Handler):
        super().__init__(plugin_runtime_handler)
        self.ctx = ctx
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

    # ================= LLM APIs (override to add validation + run_id) =================

    async def invoke_llm(
        self,
        llm_model_uuid: str,
        messages: list[provider_message.Message],
        funcs: list[resource_tool.LLMTool] = [],
        extra_args: dict[str, Any] = {},
        timeout: float | None = None,
    ) -> provider_message.Message:
        """Invoke an LLM model with permission validation and run_id."""
        self._validate_model_access(llm_model_uuid)

        effective_timeout = timeout if timeout is not None else 120.0
        resp = (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.INVOKE_LLM,
                {
                    "run_id": self.run_id,
                    "llm_model_uuid": llm_model_uuid,
                    "messages": [m.model_dump() for m in messages],
                    "funcs": [f.model_dump() for f in funcs],
                    "extra_args": extra_args,
                    "timeout": effective_timeout,
                },
                timeout=effective_timeout,
            )
        )["message"]

        return provider_message.Message.model_validate(resp)

    async def invoke_llm_stream(
        self,
        llm_model_uuid: str,
        messages: list[provider_message.Message],
        funcs: list[resource_tool.LLMTool] = [],
        extra_args: dict[str, Any] = {},
    ):
        """Invoke an LLM model with streaming, permission validation and run_id."""
        self._validate_model_access(llm_model_uuid)

        async for chunk_data in self.plugin_runtime_handler.call_action_generator(
            PluginToRuntimeAction.INVOKE_LLM_STREAM,
            {
                "run_id": self.run_id,
                "llm_model_uuid": llm_model_uuid,
                "messages": [m.model_dump() for m in messages],
                "funcs": [f.model_dump() for f in funcs],
                "extra_args": extra_args,
            },
        ):
            yield provider_message.MessageChunk.model_validate(chunk_data["chunk"])

    # ================= Tool API (different signature from parent) =================

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

        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.CALL_TOOL,
                {
                    "run_id": self.run_id,
                    "tool_name": tool_name,
                    "parameters": parameters,
                    "session": session or {},
                    "query_id": self.query_id,
                },
                timeout=180,
            )
        )["result"]

    # ================= Knowledge Base API (override to add validation) =================

    async def retrieve_knowledge(
        self,
        kb_id: str,
        query_text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve from knowledge base with permission validation.

        Uses RETRIEVE_KNOWLEDGE_BASE action (pipeline-scoped) with run_id.
        """
        self._validate_knowledge_base_access(kb_id)

        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE,
                {
                    "run_id": self.run_id,
                    "query_id": self.query_id,
                    "kb_id": kb_id,
                    "query_text": query_text,
                    "top_k": top_k,
                    "filters": filters or {},
                },
                timeout=30,
            )
        )["results"]

    # ================= Storage APIs (override to add validation) =================

    async def set_plugin_storage(self, key: str, value: bytes) -> None:
        self._validate_plugin_storage_access()
        await super().set_plugin_storage(key, value)

    async def get_plugin_storage(self, key: str) -> bytes:
        self._validate_plugin_storage_access()
        return await super().get_plugin_storage(key)

    async def get_plugin_storage_keys(self) -> list[str]:
        self._validate_plugin_storage_access()
        return await super().get_plugin_storage_keys()

    async def delete_plugin_storage(self, key: str) -> None:
        self._validate_plugin_storage_access()
        await super().delete_plugin_storage(key)

    async def set_workspace_storage(self, key: str, value: bytes) -> None:
        self._validate_workspace_storage_access()
        await super().set_workspace_storage(key, value)

    async def get_workspace_storage(self, key: str) -> bytes:
        self._validate_workspace_storage_access()
        return await super().get_workspace_storage(key)

    async def get_workspace_storage_keys(self) -> list[str]:
        self._validate_workspace_storage_access()
        return await super().get_workspace_storage_keys()

    async def delete_workspace_storage(self, key: str) -> None:
        self._validate_workspace_storage_access()
        await super().delete_workspace_storage(key)

    # ================= File API =================

    async def get_file(self, file_key: str) -> bytes:
        """Get a file with permission validation."""
        self._validate_file_access(file_key)
        return await super().get_config_file(file_key)