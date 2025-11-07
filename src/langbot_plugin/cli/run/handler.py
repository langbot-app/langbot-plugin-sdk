from __future__ import annotations

import asyncio
import os
import mimetypes
import typing
import base64
import aiofiles
from copy import deepcopy

from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.runtime.plugin.container import PluginContainer
from langbot_plugin.runtime.io.handler import Handler
from langbot_plugin.api.entities import events
from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.definition.components.command.command import Command
from langbot_plugin.api.proxies.event_context import EventContextProxy
from langbot_plugin.api.proxies.execute_context import ExecuteContextProxy


class PluginRuntimeHandler(Handler):
    """The handler for running plugins."""

    plugin_container: PluginContainer

    def __init__(
        self,
        connection: connection.Connection,
        plugin_initialize_callback: typing.Callable[
            [dict[str, typing.Any]], typing.Coroutine[typing.Any, typing.Any, None]
        ],
    ):
        super().__init__(connection)
        self.name = "FromRuntime"

        @self.action(RuntimeToPluginAction.INITIALIZE_PLUGIN)
        async def initialize_plugin(data: dict[str, typing.Any]) -> ActionResponse:
            await plugin_initialize_callback(data["plugin_settings"])
            return ActionResponse.success({})

        @self.action(RuntimeToPluginAction.GET_PLUGIN_CONTAINER)
        async def get_plugin_container(data: dict[str, typing.Any]) -> ActionResponse:
            return ActionResponse.success(self.plugin_container.model_dump())

        @self.action(RuntimeToPluginAction.GET_PLUGIN_ICON)
        async def get_plugin_icon(data: dict[str, typing.Any]) -> ActionResponse:
            icon_path = self.plugin_container.manifest.icon_rel_path
            if icon_path is None:
                return ActionResponse.success({"plugin_icon_file_key": "", "mime_type": ""})
            async with aiofiles.open(icon_path, "rb") as f:
                # icon_base64 = base64.b64encode(f.read()).decode("utf-8")
                icon_bytes = await f.read()

            mime_type = mimetypes.guess_type(icon_path)[0]

            plugin_icon_file_key = await self.send_file(icon_bytes, '')

            return ActionResponse.success(
                {"plugin_icon_file_key": plugin_icon_file_key, "mime_type": mime_type}
            )

        @self.action(RuntimeToPluginAction.EMIT_EVENT)
        async def emit_event(data: dict[str, typing.Any]) -> ActionResponse:
            """Emit an event to the plugin.

            {
                "event_context": dict[str, typing.Any],
            }
            """

            event_name = data["event_context"]["event_name"]

            if getattr(events, event_name) is None:
                return ActionResponse.error(f"Event {event_name} not found")

            args = deepcopy(data["event_context"])

            args["plugin_runtime_handler"] = self

            event_context = EventContextProxy.model_validate(args)

            emitted: bool = False

            # check if the event is registered
            for component in self.plugin_container.components:
                if component.manifest.kind == EventListener.__kind__:
                    if component.component_instance is None:
                        return ActionResponse.error("Event listener is not initialized")

                    assert isinstance(component.component_instance, EventListener)

                    if (
                        event_context.event.__class__
                        not in component.component_instance.registered_handlers
                    ):
                        continue

                    for handler in component.component_instance.registered_handlers[
                        event_context.event.__class__
                    ]:
                        await handler(event_context)
                        emitted = True

                    break

            return ActionResponse.success(
                data={
                    "emitted": emitted,
                    "event_context": event_context.model_dump(),
                }
            )

        @self.action(RuntimeToPluginAction.CALL_TOOL)
        async def call_tool(data: dict[str, typing.Any]) -> ActionResponse:
            """Call a tool."""
            tool_name = data["tool_name"]
            tool_parameters = data["tool_parameters"]

            for component in self.plugin_container.components:
                if component.manifest.kind == Tool.__kind__:
                    if component.manifest.metadata.name != tool_name:
                        continue

                    if isinstance(component.component_instance, NoneComponent):
                        return ActionResponse.error("Tool is not initialized")

                    assert isinstance(component.component_instance, Tool)

                    tool_instance = component.component_instance
                    resp = await tool_instance.call(tool_parameters)

                    return ActionResponse.success(
                        data={
                            "tool_response": resp,
                        }
                    )

            return ActionResponse.error(f"Tool {tool_name} not found")

        @self.action(RuntimeToPluginAction.EXECUTE_COMMAND)
        async def execute_command(
            data: dict[str, typing.Any],
        ) -> typing.AsyncGenerator[ActionResponse, None]:
            """Execute a command."""

            args = deepcopy(data["command_context"])
            args["plugin_runtime_handler"] = self
            command_context = ExecuteContextProxy.model_validate(args)

            for component in self.plugin_container.components:
                if component.manifest.kind == Command.__kind__:
                    if component.manifest.metadata.name != command_context.command:
                        continue

                    if isinstance(component.component_instance, NoneComponent):
                        yield ActionResponse.error("Command is not initialized")

                    command_instance = component.component_instance
                    assert isinstance(command_instance, Command)
                    async for return_value in command_instance._execute(
                        command_context
                    ):
                        yield ActionResponse.success(
                            data={
                                "command_response": return_value.model_dump(mode="json")
                            }
                        )
                    break
            else:
                yield ActionResponse.error(
                    f"Command {command_context.command} not found"
                )

    async def register_plugin(self, prod_mode: bool = False) -> dict[str, typing.Any]:
        resp = await self.call_action(
            PluginToRuntimeAction.REGISTER_PLUGIN,
            {
                "plugin_container": self.plugin_container.model_dump(),
                "prod_mode": prod_mode,
            },
        )
        return resp


# {"action": "get_plugin_container", "data": {}, "seq_id": 1}
