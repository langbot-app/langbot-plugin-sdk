# handle connection from LangBot
from __future__ import annotations

import base64
import json
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

            result = {
                "plugins": [
                    plugin.model_dump() for plugin in self.context.plugin_mgr.plugins
                ]
            }

            return handler.ActionResponse.success(result)

        @self.action(LangBotToRuntimeAction.GET_PLUGIN_INFO)
        async def get_plugin_info(data: dict[str, Any]) -> handler.ActionResponse:
            author = data["author"]
            plugin_name = data["plugin_name"]
            for plugin in self.context.plugin_mgr.plugins:
                if (
                    plugin.manifest.metadata.author == author
                    and plugin.manifest.metadata.name == plugin_name
                ):
                    result = {"plugin": plugin.model_dump()}

                    return handler.ActionResponse.success(result)

            return handler.ActionResponse.success({"plugin": None})

        @self.action(LangBotToRuntimeAction.GET_PLUGIN_ICON)
        async def get_plugin_icon(data: dict[str, Any]) -> handler.ActionResponse:
            author = data["plugin_author"]
            plugin_name = data["plugin_name"]
            (
                plugin_icon_bytes,
                mime_type,
            ) = await self.context.plugin_mgr.get_plugin_icon(author, plugin_name)

            plugin_icon_file_key = await self.send_file(plugin_icon_bytes, "")

            return handler.ActionResponse.success(
                {"plugin_icon_file_key": plugin_icon_file_key, "mime_type": mime_type}
            )

        @self.action(LangBotToRuntimeAction.INSTALL_PLUGIN)
        async def install_plugin(
            data: dict[str, Any],
        ) -> AsyncGenerator[handler.ActionResponse, None]:
            install_source = plugin_mgr_module.PluginInstallSource(
                data["install_source"]
            )
            install_info = data["install_info"]

            if (
                install_source == plugin_mgr_module.PluginInstallSource.LOCAL
                or install_source == plugin_mgr_module.PluginInstallSource.GITHUB
            ):
                install_info["plugin_file"] = await self.read_local_file(
                    install_info["plugin_file_key"]
                )
                await self.delete_local_file(install_info["plugin_file_key"])

            async for resp in self.context.plugin_mgr.install_plugin(
                install_source, install_info
            ):
                yield handler.ActionResponse.success(resp)
            yield handler.ActionResponse.success({"current_action": "plugin installed"})

        @self.action(LangBotToRuntimeAction.RESTART_PLUGIN)
        async def restart_plugin(
            data: dict[str, Any],
        ) -> AsyncGenerator[handler.ActionResponse, None]:
            async for resp in self.context.plugin_mgr.restart_plugin(
                data["plugin_author"], data["plugin_name"]
            ):
                yield handler.ActionResponse.success(resp)
            yield handler.ActionResponse.success({"current_action": "plugin restarted"})

        @self.action(LangBotToRuntimeAction.DELETE_PLUGIN)
        async def remove_plugin(
            data: dict[str, Any],
        ) -> AsyncGenerator[handler.ActionResponse, None]:
            async for resp in self.context.plugin_mgr.delete_plugin(
                data["plugin_author"], data["plugin_name"]
            ):
                yield handler.ActionResponse.success(resp)
            yield handler.ActionResponse.success({"current_action": "plugin removed"})

        @self.action(LangBotToRuntimeAction.UPGRADE_PLUGIN)
        async def upgrade_plugin(
            data: dict[str, Any],
        ) -> AsyncGenerator[handler.ActionResponse, None]:
            async for resp in self.context.plugin_mgr.upgrade_plugin(
                data["plugin_author"], data["plugin_name"]
            ):
                yield handler.ActionResponse.success(resp)
            yield handler.ActionResponse.success({"current_action": "plugin upgraded"})

        @self.action(LangBotToRuntimeAction.EMIT_EVENT)
        async def emit_event(data: dict[str, Any]) -> handler.ActionResponse:
            event_context_data = data["event_context"]
            event_context = EventContext.model_validate(event_context_data)
            include_plugins = data.get("include_plugins")

            emitted_plugins, event_context = await self.context.plugin_mgr.emit_event(
                event_context, include_plugins
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
            include_plugins = data.get("include_plugins")
            tools = await self.context.plugin_mgr.list_tools(include_plugins)
            return handler.ActionResponse.success(
                {"tools": [tool.model_dump() for tool in tools]}
            )

        @self.action(LangBotToRuntimeAction.CALL_TOOL)
        async def call_tool(data: dict[str, Any]) -> handler.ActionResponse:
            tool_name = data["tool_name"]
            tool_parameters = data["tool_parameters"]
            include_plugins = data.get("include_plugins")

            resp = await self.context.plugin_mgr.call_tool(tool_name, tool_parameters, include_plugins)

            return handler.ActionResponse.success(
                {
                    "tool_response": resp,
                }
            )

        @self.action(LangBotToRuntimeAction.LIST_COMMANDS)
        async def list_commands(data: dict[str, Any]) -> handler.ActionResponse:
            include_plugins = data.get("include_plugins")
            commands = await self.context.plugin_mgr.list_commands(include_plugins)
            return handler.ActionResponse.success(
                {"commands": [command.model_dump() for command in commands]}
            )

        @self.action(LangBotToRuntimeAction.EXECUTE_COMMAND)
        async def execute_command(
            data: dict[str, Any],
        ) -> AsyncGenerator[handler.ActionResponse, None]:
            command_context = ExecuteContext.model_validate(data["command_context"])
            include_plugins = data.get("include_plugins")
            async for resp in self.context.plugin_mgr.execute_command(command_context, include_plugins):
                yield handler.ActionResponse.success(resp.model_dump(mode="json"))


# {"action": "ping", "data": {}, "seq_id": 1}
# {"code": 0, "message": "ok", "data": {"msg": "hello"}, "seq_id": 1}
