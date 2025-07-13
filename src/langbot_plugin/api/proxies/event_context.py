from __future__ import annotations

from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.api.entities.context import EventContext
from langbot_plugin.runtime.io.handler import Handler
import pydantic


class EventContextProxy(EventContext):
    """The proxy for event context."""

    plugin_runtime_handler: Handler = pydantic.Field(exclude=True)

    async def reply(
        self, message_chain: platform_message.MessageChain, quote_origin: bool = False
    ):
        """Reply to the message sender"""
        return await self.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.REPLY_MESSAGE,
            {
                "eid": self.eid,
                "message_chain": message_chain.model_dump(mode="json"),
                "quote_origin": quote_origin,
            },
        )

    class Config:
        arbitrary_types_allowed = True
