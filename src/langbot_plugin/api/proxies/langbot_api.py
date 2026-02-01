from __future__ import annotations

import base64
from typing import Any

from langbot_plugin.runtime.io.handler import Handler
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.api.entities.builtin.provider import message as provider_message
from langbot_plugin.api.entities.builtin.resource import tool as resource_tool


class LangBotAPIProxy:
    """The proxy for langbot API."""

    plugin_runtime_handler: Handler

    def __init__(self, plugin_runtime_handler: Handler):
        self.plugin_runtime_handler = plugin_runtime_handler

    async def get_langbot_version(self) -> str:
        """Get the langbot version"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_LANGBOT_VERSION, {}
            )
        )["version"]

    async def get_bots(self) -> list[str]:
        """Get all bots"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_BOTS, {}
            )
        )["bots"]

    async def get_bot_info(self, bot_uuid: str) -> dict[str, Any]:
        """Get a bot info"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_BOT_INFO, {"bot_uuid": bot_uuid}
            )
        )["bot"]

    async def send_message(
        self,
        bot_uuid: str,
        target_type: str,
        target_id: str,
        message_chain: platform_message.MessageChain,
    ) -> None:
        """Send a message to a bot

        Args:
            bot_uuid: The UUID of the bot
            target_type: The type of the target, can be "group", "person"
            target_id: The ID of the target
            message_chain: The message chain to send
        """
        await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.SEND_MESSAGE,
            {
                "bot_uuid": bot_uuid,
                "target_type": target_type,
                "target_id": target_id,
                "message_chain": message_chain.model_dump(),
            },
        )

    async def get_llm_models(self) -> list[str]:
        """Get all LLM models"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_LLM_MODELS, {}
            )
        )["llm_models"]

    async def invoke_llm(
        self,
        llm_model_uuid: str,
        messages: list[provider_message.Message],
        funcs: list[resource_tool.LLMTool] = [],
        extra_args: dict[str, Any] = {},
    ) -> provider_message.Message:
        """Invoke an LLM model"""
        resp = (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.INVOKE_LLM,
                {
                    "llm_model_uuid": llm_model_uuid,
                    "messages": [m.model_dump() for m in messages],
                    "funcs": [f.model_dump() for f in funcs],
                    "extra_args": extra_args,
                },
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
        """Invoke an LLM model with streaming response

        Args:
            llm_model_uuid: The UUID of the LLM model to use
            messages: List of conversation messages
            funcs: List of tools available to the LLM
            extra_args: Extra arguments for the LLM provider

        Yields:
            MessageChunk: Streamed message chunks from the LLM
        """
        async for chunk_data in self.plugin_runtime_handler.call_action_generator(
            PluginToRuntimeAction.INVOKE_LLM_STREAM,
            {
                "llm_model_uuid": llm_model_uuid,
                "messages": [m.model_dump() for m in messages],
                "funcs": [f.model_dump() for f in funcs],
                "extra_args": extra_args,
            },
        ):
            yield provider_message.MessageChunk.model_validate(chunk_data["chunk"])

    async def set_plugin_storage(self, key: str, value: bytes) -> None:
        """Set a plugin storage value"""
        await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.SET_PLUGIN_STORAGE,
            {"key": key, "value_base64": base64.b64encode(value).decode("utf-8")},
        )

    async def get_plugin_storage(self, key: str) -> bytes:
        """Get a plugin storage value"""
        resp = (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_PLUGIN_STORAGE, {"key": key}
            )
        )["value_base64"]

        return base64.b64decode(resp)

    async def get_plugin_storage_keys(self) -> list[str]:
        """Get all plugin storage keys"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_PLUGIN_STORAGE_KEYS, {}
            )
        )["keys"]

    async def delete_plugin_storage(self, key: str) -> None:
        """Delete a plugin storage value"""
        await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.DELETE_PLUGIN_STORAGE, {"key": key}
        )

    async def set_workspace_storage(self, key: str, value: bytes) -> None:
        """Set a workspace storage value"""
        await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.SET_WORKSPACE_STORAGE,
            {"key": key, "value_base64": base64.b64encode(value).decode("utf-8")},
        )

    async def get_workspace_storage(self, key: str) -> bytes:
        """Get a workspace storage value"""
        resp = (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_WORKSPACE_STORAGE, {"key": key}
            )
        )["value_base64"]

        return base64.b64decode(resp)

    async def get_workspace_storage_keys(self) -> list[str]:
        """Get all workspace storage keys"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_WORKSPACE_STORAGE_KEYS, {}
            )
        )["keys"]

    async def delete_workspace_storage(self, key: str) -> None:
        """Delete a workspace storage value"""
        await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.DELETE_WORKSPACE_STORAGE, {"key": key}
        )

    async def get_config_file(self, file_key: str) -> bytes:
        """Get a config file by file key

        Args:
            file_key: The file key from plugin config (file or array[file] type)

        Returns:
            The file content as bytes
        """
        resp = (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_CONFIG_FILE, {"file_key": file_key}
            )
        )["file_base64"]

        return base64.b64decode(resp)

    async def list_plugins_manifest(self) -> list[str]:
        """List all plugins"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.LIST_PLUGINS_MANIFEST, {}
            )
        )["plugins"]

    async def list_commands(self) -> list[str]:
        """List all commands"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.LIST_COMMANDS, {}
            )
        )["commands"]

    async def list_tools(self) -> list[str]:
        """List all tools"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.LIST_TOOLS, {}
            )
        )["tools"]

    async def call_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        session_data: dict[str, Any],
        query_id: int,
    ) -> dict[str, Any]:
        """Call a tool by name

        Args:
            tool_name: Name of the tool to call
            parameters: Parameters for the tool
            session_data: Session information
            query_id: Query ID

        Returns:
            Tool execution result as dict
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.CALL_TOOL,
                {
                    "tool_name": tool_name,
                    "parameters": parameters,
                    "session": session_data,
                    "query_id": query_id,
                },
            )
        )["result"]

    async def retrieve_knowledge(
        self,
        kb_uuid: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Retrieve knowledge from a knowledge base

        Args:
            kb_uuid: UUID of the knowledge base
            query: Query text for retrieval
            top_k: Number of top results to return

        Returns:
            List of retrieval results, each containing:
                - id: Result ID
                - content: List of ContentElement
                - metadata: Additional metadata
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.RETRIEVE_KNOWLEDGE,
                {
                    "kb_uuid": kb_uuid,
                    "query": query,
                    "top_k": top_k,
                },
            )
        )["results"]

    async def invoke_embedding(
        self,
        embedding_model_uuid: str,
        texts: list[str],
    ) -> list[list[float]]:
        """Invoke an embedding model to generate embeddings

        Args:
            embedding_model_uuid: UUID of the embedding model
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.INVOKE_EMBEDDING,
                {
                    "embedding_model_uuid": embedding_model_uuid,
                    "texts": texts,
                },
            )
        )["embeddings"]
