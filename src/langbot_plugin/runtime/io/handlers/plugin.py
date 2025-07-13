# handle connection to/from plugin
from __future__ import annotations

from typing import Any, AsyncGenerator

from langbot_plugin.runtime.io import handler, connection
from langbot_plugin.entities.io.actions.enums import (
    PluginToRuntimeAction,
    RuntimeToPluginAction,
)
from langbot_plugin.runtime import context as context_module


class PluginConnectionHandler(handler.Handler):
    """The handler for plugin connection."""

    context: context_module.RuntimeContext

    def __init__(
        self, connection: connection.Connection, context: context_module.RuntimeContext
    ):
        async def disconnect_callback(hdl: handler.Handler):
            for plugin_container in self.context.plugin_mgr.plugins:
                if plugin_container._runtime_plugin_handler == self:
                    print(
                        f"Removing plugin {plugin_container.manifest.metadata.name} due to disconnect"
                    )
                    await self.context.plugin_mgr.remove_plugin(plugin_container)
                    break

        super().__init__(connection, disconnect_callback)
        self.context = context

        @self.action(PluginToRuntimeAction.REGISTER_PLUGIN)
        async def register_plugin(data: dict[str, Any]) -> handler.ActionResponse:
            await self.context.plugin_mgr.register_plugin(
                self, data["plugin_container"]
            )
            return handler.ActionResponse.success({})

        @self.action(PluginToRuntimeAction.REPLY_MESSAGE)
        async def reply_message(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.REPLY_MESSAGE,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

    async def initialize_plugin(
        self, plugin_settings: dict[str, Any]
    ) -> dict[str, Any]:
        resp = await self.call_action(
            RuntimeToPluginAction.INITIALIZE_PLUGIN,
            {"plugin_settings": plugin_settings},
        )

        return resp

    async def get_plugin_container(self) -> dict[str, Any]:
        resp = await self.call_action(RuntimeToPluginAction.GET_PLUGIN_CONTAINER, {})

        return resp

    async def emit_event(self, event_context: dict[str, Any]) -> dict[str, Any]:
        resp = await self.call_action(
            RuntimeToPluginAction.EMIT_EVENT, {"event_context": event_context}
        )

        return resp

    async def call_tool(
        self, tool_name: str, tool_parameters: dict[str, Any]
    ) -> dict[str, Any]:
        resp = await self.call_action(
            RuntimeToPluginAction.CALL_TOOL,
            {"tool_name": tool_name, "tool_parameters": tool_parameters},
        )

        return resp

    async def execute_command(
        self, command_context: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        gen = self.call_action_generator(
            RuntimeToPluginAction.EXECUTE_COMMAND, {"command_context": command_context}
        )

        async for resp in gen:
            yield resp
