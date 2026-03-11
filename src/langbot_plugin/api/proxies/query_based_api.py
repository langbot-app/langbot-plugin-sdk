from __future__ import annotations

from typing import Any

from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.runtime.io.handler import Handler
import pydantic


class QueryBasedAPIProxy(pydantic.BaseModel):
    """The proxy for query based API."""

    query_id: int

    plugin_runtime_handler: Handler = pydantic.Field(exclude=True)

    async def reply(
        self, message_chain: platform_message.MessageChain, quote_origin: bool = False
    ):
        """Reply to the message sender"""
        return await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.REPLY_MESSAGE,
            {
                "query_id": self.query_id,
                "message_chain": message_chain.model_dump(mode="json"),
                "quote_origin": quote_origin,
            },
            timeout=180,
        )

    async def get_bot_uuid(self) -> str:
        """Get the bot uuid"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_BOT_UUID,
                {
                    "query_id": self.query_id,
                },
            )
        )["bot_uuid"]

    async def set_query_var(self, key: str, value: Any):
        """Set a query variable"""
        return await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.SET_QUERY_VAR,
            {
                "query_id": self.query_id,
                "key": key,
                "value": value,
            },
        )

    async def get_query_var(self, key: str) -> Any:
        """Get a query variable"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_QUERY_VAR,
                {
                    "query_id": self.query_id,
                    "key": key,
                },
            )
        )["value"]

    async def get_query_vars(self) -> dict[str, Any]:
        """Get all query variables"""
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.GET_QUERY_VARS,
                {
                    "query_id": self.query_id,
                },
            )
        )["vars"]

    async def create_new_conversation(self) -> dict[str, Any]:
        """Create a new conversation"""
        return await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.CREATE_NEW_CONVERSATION,
            {
                "query_id": self.query_id,
            },
        )

    async def list_pipeline_knowledge_bases(self) -> list[dict[str, Any]]:
        """List knowledge bases configured for the current pipeline.

        Returns a list of dicts, each containing:
        - uuid: Knowledge base UUID
        - name: Knowledge base name
        - description: Knowledge base description
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.LIST_PIPELINE_KNOWLEDGE_BASES,
                {
                    "query_id": self.query_id,
                },
            )
        )["knowledge_bases"]

    async def retrieve_knowledge(
        self,
        kb_id: str,
        query_text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant documents from a knowledge base.

        The kb_id must be in the current pipeline's configured knowledge bases,
        otherwise an error is returned.

        Args:
            kb_id: Knowledge base UUID (from list_pipeline_knowledge_bases result)
            query_text: Search query text
            top_k: Number of results to return (default: 5)
            filters: Optional metadata filters for retrieval

        Returns a list of retrieval result entries.
        """
        return (
            await self.plugin_runtime_handler.call_action(
                PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE,
                {
                    "query_id": self.query_id,
                    "kb_id": kb_id,
                    "query_text": query_text,
                    "top_k": top_k,
                    "filters": filters or {},
                },
            )
        )["results"]

    class Config:
        arbitrary_types_allowed = True
