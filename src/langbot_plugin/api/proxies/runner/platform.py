"""Platform APIs with the same signatures as the shared plugin API."""

from typing import Any
from langbot_plugin.api.entities.builtin.platform.message import MessageChain
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction


class RunnerPlatformAPIMixin:
    async def call_platform_api(
        self, bot_uuid: str, action: str, params: dict[str, Any] | None = None
    ) -> Any:
        response = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.CALL_PLATFORM_API,
            {
                "run_id": self.run_id,
                "bot_uuid": bot_uuid,
                "action": action,
                "params": params or {},
            },
            self._bounded_timeout(default=180.0),
        )
        return self._expect_key(
            response, "result", PluginToRuntimeAction.CALL_PLATFORM_API
        )

    async def send_message(
        self,
        bot_uuid: str,
        target_type: str,
        target_id: str,
        message_chain: MessageChain,
    ) -> Any:
        return await self.call_platform_api(
            bot_uuid,
            "send_message",
            {
                "target_type": target_type,
                "target_id": target_id,
                "message": message_chain.model_dump(mode="json"),
            },
        )

    async def reply_message(
        self, message_chain: MessageChain, quote_origin: bool = False
    ) -> Any:
        response = await self._api.plugin_runtime_handler.call_action(
            PluginToRuntimeAction.CALL_PLATFORM_API,
            {
                "run_id": self.run_id,
                "action": "send_message",
                "context_tool": "event_reply",
                "params": {
                    "message": message_chain.model_dump(mode="json"),
                    "quote_origin": quote_origin,
                },
            },
            self._bounded_timeout(default=180.0),
        )
        return self._expect_key(
            response, "result", PluginToRuntimeAction.CALL_PLATFORM_API
        )
