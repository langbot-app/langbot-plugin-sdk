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

    # ================= RAG Capability APIs =================

    async def invoke_embedding(self, embedding_model_uuid: str, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using Host's embedding model.

        Args:
            embedding_model_uuid: The UUID of the embedding model to use.
            texts: List of texts to embed.

        Returns:
            List of embedding vectors, one per input text.
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.INVOKE_EMBEDDING,
                {
                    "embedding_model_uuid": embedding_model_uuid,
                    "texts": texts
                }
            )
        )["vectors"]

    async def vector_upsert(
        self, 
        collection_id: str, 
        vectors: list[list[float]], 
        ids: list[str],
        metadata: list[dict[str, Any]] | None = None
    ) -> None:
        """Upsert vectors to Host's vector store.
        
        Args:
            collection_id: Target collection ID.
            vectors: List of vectors.
            ids: List of unique IDs for vectors.
            metadata: Optional list of metadata dicts corresponding to vectors.
        """
        await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.VECTOR_UPSERT,
            {
                "collection_id": collection_id,
                "vectors": vectors,
                "ids": ids,
                "metadata": metadata
            }
        )

    async def vector_search(
        self,
        collection_id: str,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search similar vectors in Host's vector store.

        Args:
            collection_id: Target collection ID.
            query_vector: Query vector for similarity search.
            top_k: Number of results to return.
            filters: Optional metadata filters.

        Returns:
            List of search results (dict with id, score, metadata).
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.VECTOR_SEARCH,
                {
                    "collection_id": collection_id,
                    "query_vector": query_vector,
                    "top_k": top_k,
                    "filters": filters,
                }
            )
        )["results"]

    async def vector_delete(
        self,
        collection_id: str,
        file_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None
    ) -> int:
        """Delete vectors from Host's vector store.

        Args:
            collection_id: Target collection ID.
            file_ids: File IDs whose associated vectors should be deleted.
            filters: Optional metadata filters for deletion.

        Returns:
            Number of deleted items.
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.VECTOR_DELETE,
                {
                    "collection_id": collection_id,
                    "file_ids": file_ids,
                    "filters": filters
                }
            )
        )["count"]

    async def get_rag_file_stream(self, storage_path: str) -> bytes:
        """Get file content from Host's storage.

        Args:
            storage_path: Logic path in FileObject.

        Returns:
            File content bytes.
        """
        resp = await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_RAG_FILE_STREAM,
            {"storage_path": storage_path}
        )
        return base64.b64decode(resp["content_base64"])
