# handle connection from LangBot
from __future__ import annotations

from typing import Any, AsyncGenerator

from langbot_plugin.runtime.io import handler, connection
from langbot_plugin.entities.io.actions.enums import (
    CommonAction,
    LangBotToRuntimeAction,
    RuntimeToPluginAction,
)
from langbot_plugin.runtime import context as context_module
from langbot_plugin.api.entities.context import EventContext
from langbot_plugin.api.entities.builtin.command.context import ExecuteContext
import traceback
from langbot_plugin.runtime.plugin import mgr as plugin_mgr_module

class ControlConnectionHandler(handler.Handler):
    """The handler for control connection."""

    context: context_module.RuntimeContext

    def __init__(
        self, connection: connection.Connection, context: context_module.RuntimeContext
    ):
        super().__init__(connection)
        self.name = "FromLangBot"
        self.context = context

        @self.action(CommonAction.PING)
        async def ping(data: dict[str, Any]) -> handler.ActionResponse:
            return handler.ActionResponse.success({"message": "pong"})

        @self.action(LangBotToRuntimeAction.LIST_PLUGINS)
        async def list_plugins(data: dict[str, Any]) -> handler.ActionResponse:
            return handler.ActionResponse.success(
                {
                    "plugins": [
                        plugin.model_dump()
                        for plugin in self.context.plugin_mgr.plugins
                    ]
                }
            )

        @self.action(LangBotToRuntimeAction.GET_PLUGIN_INFO)
        async def get_plugin_info(data: dict[str, Any]) -> handler.ActionResponse:
            author = data["author"]
            plugin_name = data["plugin_name"]
            for plugin in self.context.plugin_mgr.plugins:
                if plugin.manifest.metadata.author == author and plugin.manifest.metadata.name == plugin_name:
                    return handler.ActionResponse.success({"plugin": plugin.model_dump()})
            return handler.ActionResponse.success({"plugin": None})

        @self.action(LangBotToRuntimeAction.INSTALL_PLUGIN)
        async def install_plugin(data: dict[str, Any]) -> AsyncGenerator[handler.ActionResponse, None]:
            install_source = plugin_mgr_module.PluginInstallSource(data["install_source"])
            install_info = data["install_info"]
            async for resp in self.context.plugin_mgr.install_plugin(install_source, install_info):
                yield handler.ActionResponse.success(resp)
            yield handler.ActionResponse.success({"current_action": "plugin installed"})

        @self.action(LangBotToRuntimeAction.RESTART_PLUGIN)
        async def restart_plugin(data: dict[str, Any]) -> AsyncGenerator[handler.ActionResponse, None]:
            async for resp in self.context.plugin_mgr.restart_plugin(data["plugin_author"], data["plugin_name"]):
                yield handler.ActionResponse.success(resp)
            yield handler.ActionResponse.success({"current_action": "plugin restarted"})

        @self.action(LangBotToRuntimeAction.DELETE_PLUGIN)
        async def remove_plugin(data: dict[str, Any]) -> AsyncGenerator[handler.ActionResponse, None]:
            async for resp in self.context.plugin_mgr.delete_plugin(data["plugin_author"], data["plugin_name"]):
                yield handler.ActionResponse.success(resp)
            yield handler.ActionResponse.success({"current_action": "plugin removed"})

        @self.action(LangBotToRuntimeAction.UPGRADE_PLUGIN)
        async def upgrade_plugin(data: dict[str, Any]) -> AsyncGenerator[handler.ActionResponse, None]:
            async for resp in self.context.plugin_mgr.upgrade_plugin(data["plugin_author"], data["plugin_name"]):
                yield handler.ActionResponse.success(resp)
            yield handler.ActionResponse.success({"current_action": "plugin upgraded"})

        @self.action(LangBotToRuntimeAction.EMIT_EVENT)
        async def emit_event(data: dict[str, Any]) -> handler.ActionResponse:
            event_context_data = data["event_context"]
            event_context = EventContext.model_validate(event_context_data)

            emitted_plugins, event_context = await self.context.plugin_mgr.emit_event(
                event_context
            )

            event_context_dump = event_context.model_dump()

            return handler.ActionResponse.success(
                {
                    "emitted_plugins": [
                        plugin.model_dump() for plugin in emitted_plugins
                    ],
                    "event_context": event_context_dump,
                }
            )

        @self.action(LangBotToRuntimeAction.LIST_TOOLS)
        async def list_tools(data: dict[str, Any]) -> handler.ActionResponse:
            tools = await self.context.plugin_mgr.list_tools()
            return handler.ActionResponse.success(
                {"tools": [tool.model_dump() for tool in tools]}
            )

        @self.action(LangBotToRuntimeAction.CALL_TOOL)
        async def call_tool(data: dict[str, Any]) -> handler.ActionResponse:
            tool_name = data["tool_name"]
            tool_parameters = data["tool_parameters"]

            resp = await self.context.plugin_mgr.call_tool(tool_name, tool_parameters)

            return handler.ActionResponse.success(
                {
                    "tool_response": resp,
                }
            )

        @self.action(LangBotToRuntimeAction.LIST_COMMANDS)
        async def list_commands(data: dict[str, Any]) -> handler.ActionResponse:
            commands = await self.context.plugin_mgr.list_commands()
            return handler.ActionResponse.success(
                {"commands": [command.model_dump() for command in commands]}
            )

        @self.action(LangBotToRuntimeAction.EXECUTE_COMMAND)
        async def execute_command(
            data: dict[str, Any],
        ) -> AsyncGenerator[handler.ActionResponse, None]:
            command_context = ExecuteContext.model_validate(data["command_context"])
            async for resp in self.context.plugin_mgr.execute_command(command_context):
                yield handler.ActionResponse.success(resp.model_dump(mode="json"))


# {"action": "ping", "data": {}, "seq_id": 1}
# {"code": 0, "message": "ok", "data": {"msg": "hello"}, "seq_id": 1}
