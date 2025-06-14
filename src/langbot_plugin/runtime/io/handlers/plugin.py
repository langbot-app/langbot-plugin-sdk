# handle connection to/from plugin
from __future__ import annotations

from typing import Any

from langbot_plugin.runtime.io import handler, connection
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction, RuntimeToLangBotAction, RuntimeToPluginAction
from langbot_plugin.runtime import context as context_module


class PluginConnectionHandler(handler.Handler):
    """The handler for plugin connection."""
    
    context: context_module.RuntimeContext

    def __init__(self, connection: connection.Connection, context: context_module.RuntimeContext):
        super().__init__(connection)
        self.context = context

        @self.action(PluginToRuntimeAction.REGISTER_PLUGIN)
        async def register_plugin(data: dict[str, Any]) -> handler.ActionResponse:
            await self.context.plugin_mgr.register_plugin(self, data["plugin_container"])
            return handler.ActionResponse.success({})

        @self.action(PluginToRuntimeAction.GET_PLUGIN_SETTINGS)
        async def get_plugin_settings(data: dict[str, Any]) -> handler.ActionResponse:
            lb_resp = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.GET_PLUGIN_SETTINGS,
                data
            )

            return handler.ActionResponse.success(lb_resp)

    async def get_plugin_container(self) -> dict[str, Any]:
        resp = await self.call_action(
            RuntimeToPluginAction.GET_PLUGIN_CONTAINER,
            {}
        )

        return resp