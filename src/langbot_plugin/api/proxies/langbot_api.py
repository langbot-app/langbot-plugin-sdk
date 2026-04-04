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
        timeout: float | None = None,
    ) -> provider_message.Message:
        """Invoke an LLM model"""
        effective_timeout = timeout if timeout is not None else 120.0
        resp = (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.INVOKE_LLM,
                {
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

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools.

        Returns:
            List of tool info dicts, each containing:
            - name: Tool name (plugin_author/plugin_name/tool_name format)
            - label: I18n label dict
            - description: I18n description dict
            - parameters: JSON Schema of tool parameters
            - spec: Full tool spec
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.LIST_TOOLS, {}
            )
        )["tools"]

    async def get_tool_detail(self, tool_name: str) -> dict[str, Any]:
        """Get detailed information about a specific tool.

        Args:
            tool_name: The name of the tool to get details for.

        Returns:
            Tool detail dict containing name, label, description, parameters, spec.

        Raises:
            Exception: If the tool is not found.
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_TOOL_DETAIL, {"tool_name": tool_name}
            )
        )["tool"]

    async def call_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        session: dict[str, Any],
        query_id: int,
    ) -> dict[str, Any]:
        """Call a specific tool.

        Args:
            tool_name: The name of the tool to call.
            parameters: The parameters to pass to the tool.
            session: The current session dict.
            query_id: The current query ID.

        Returns:
            Tool response dict.
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.CALL_TOOL,
                {
                    "tool_name": tool_name,
                    "tool_parameters": parameters,
                    "session": session,
                    "query_id": query_id,
                },
                timeout=180,
            )
        )["tool_response"]

    # ================= RAG Capability APIs =================

    async def invoke_embedding(
        self, embedding_model_uuid: str, texts: list[str]
    ) -> list[list[float]]:
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
                {"embedding_model_uuid": embedding_model_uuid, "texts": texts},
                timeout=60,
            )
        )["vectors"]

    async def vector_upsert(
        self,
        collection_id: str,
        vectors: list[list[float]],
        ids: list[str],
        metadata: list[dict[str, Any]] | None = None,
        documents: list[str] | None = None,
    ) -> None:
        """Upsert vectors to Host's vector store.

        Args:
            collection_id: Target collection ID.
            vectors: List of vectors.
            ids: List of unique IDs for vectors.
            metadata: Optional list of metadata dicts corresponding to vectors.
            documents: Optional raw text documents. Required for full-text
                and hybrid search in backends that support them.
        """
        data: dict[str, Any] = {
            "collection_id": collection_id,
            "vectors": vectors,
            "ids": ids,
            "metadata": metadata,
        }
        if documents is not None:
            data["documents"] = documents
        await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.VECTOR_UPSERT,
            data,
            timeout=60,
        )

    async def vector_search(
        self,
        collection_id: str,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        search_type: str = "vector",
        query_text: str = "",
        vector_weight: float | None = None,
    ) -> list[dict[str, Any]]:
        """Search similar vectors in Host's vector store.

        Args:
            collection_id: Target collection ID.
            query_vector: Query vector for similarity search.
            top_k: Number of results to return.
            filters: Optional metadata filters.
            search_type: One of 'vector', 'full_text', 'hybrid'.
            query_text: Raw query text, used for full_text and hybrid search.
            vector_weight: Weight for vector search in hybrid mode (0.0–1.0).
                ``None`` means use equal weights (backward compatible).

        Returns:
            List of search results (dict with id, distance, metadata).
            Some hosts may also include an optional score field, but distance
            is the stable field and lower values mean more similar results.
        """
        data = {
            "collection_id": collection_id,
            "query_vector": query_vector,
            "top_k": top_k,
            "filters": filters,
            "search_type": search_type,
            "query_text": query_text,
            "vector_weight": vector_weight,
        }
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.VECTOR_SEARCH,
                data,
                timeout=30,
            )
        )["results"]

    async def vector_delete(
        self,
        collection_id: str,
        file_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
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
                    "filters": filters,
                },
                timeout=30,
            )
        )["count"]

    async def vector_list(
        self,
        collection_id: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List vectors from Host's vector store by metadata filter.

        Args:
            collection_id: Target collection ID.
            filters: Optional metadata filters.
            limit: Maximum number of items to return.
            offset: Number of items to skip for pagination.

        Returns:
            Dict with 'items' (list of dicts with id, document, metadata)
            and 'total' (total count matching the filter, best-effort).
        """
        return await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.VECTOR_LIST,
            {
                "collection_id": collection_id,
                "filters": filters,
                "limit": limit,
                "offset": offset,
            },
            timeout=30,
        )

    async def get_knowledge_file_stream(self, storage_path: str) -> bytes:
        """Get file content from Host's storage.

        Args:
            storage_path: Logic path in FileObject.

        Returns:
            File content bytes.
        """
        resp = await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.GET_KNOWLEDEGE_FILE_STREAM,
            {"storage_path": storage_path},
        )
        # File was transferred via FILE_CHUNK; read from local temp
        file_key = resp["file_key"]
        file_bytes = await self.plugin_runtime_handler.read_local_file(file_key)
        await self.plugin_runtime_handler.delete_local_file(file_key)
        return file_bytes

    # ================= Knowledge Base APIs =================

    async def list_knowledge_bases(self) -> list[dict[str, Any]]:
        """List all knowledge bases available in the LangBot instance.

        Unlike query-based ``list_pipeline_knowledge_bases``, this API is
        globally available and not restricted to a specific pipeline's
        configured knowledge bases.

        Returns:
            List of dicts, each containing:
            - uuid: Knowledge base UUID
            - name: Knowledge base name
            - description: Knowledge base description
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.LIST_KNOWLEDGE_BASES, {}
            )
        )["knowledge_bases"]

    async def retrieve_knowledge(
        self,
        kb_id: str,
        query_text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant documents from any knowledge base.

        Unlike query-based ``retrieve_knowledge``, this API is globally
        available and can access any knowledge base without pipeline
        restrictions.

        Args:
            kb_id: Knowledge base UUID
            query_text: Search query text
            top_k: Number of results to return (default: 5)
            filters: Optional metadata filters for retrieval

        Returns:
            List of retrieval result entries.
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.RETRIEVE_KNOWLEDGE,
                {
                    "kb_id": kb_id,
                    "query_text": query_text,
                    "top_k": top_k,
                    "filters": filters or {},
                },
                timeout=30,
            )
        )["results"]

    # ================= Parser Capability APIs =================

    async def list_parsers(self, mime_type: str | None = None) -> list[dict[str, Any]]:
        """List available Parser plugins.

        Args:
            mime_type: Optional MIME type to filter parsers by.

        Returns:
            List of parser metadata dicts.
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.LIST_PARSERS,
                {"mime_type": mime_type},
            )
        )["parsers"]

    async def invoke_parser(
        self,
        plugin_author: str,
        plugin_name: str,
        storage_path: str,
        mime_type: str,
        filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a Parser plugin to parse a document.

        Args:
            plugin_author: Author of the parser plugin.
            plugin_name: Name of the parser plugin.
            storage_path: Path to the file in Host's storage system.
            mime_type: MIME type of the file.
            filename: Original filename.
            metadata: Optional extra metadata.

        Returns:
            Parse result dict with text, sections, and metadata.
        """
        return await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.INVOKE_PARSER,
            {
                "plugin_author": plugin_author,
                "plugin_name": plugin_name,
                "storage_path": storage_path,
                "mime_type": mime_type,
                "filename": filename,
                "metadata": metadata or {},
            },
            timeout=300,
        )
