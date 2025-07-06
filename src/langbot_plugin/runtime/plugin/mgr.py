from __future__ import annotations

import typing
from langbot_plugin.runtime.plugin import container as runtime_plugin_container
from langbot_plugin.runtime.io.handlers import plugin as runtime_plugin_handler_cls
from langbot_plugin.runtime import context as context_module
from langbot_plugin.api.entities.context import EventContext
from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.entities.io.actions.enums import RuntimeToLangBotAction


class PluginManager:
    """The manager for plugins."""

    context: context_module.RuntimeContext

    plugin_handlers: list[runtime_plugin_handler_cls.PluginConnectionHandler] = []

    plugins: list[runtime_plugin_container.PluginContainer] = []

    def __init__(self, context: context_module.RuntimeContext):
        self.context = context

    async def add_plugin_handler(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
    ):
        self.plugin_handlers.append(handler)

        await handler.run()

    async def remove_plugin_handler(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
    ):
        if handler not in self.plugin_handlers:
            return
        
        self.plugin_handlers.remove(handler)

    async def register_plugin(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
        container_data: dict[str, typing.Any],
    ):
        plugin_container = runtime_plugin_container.PluginContainer.from_dict(
            container_data
        )

        # get plugin settings from LangBot
        plugin_settings = await self.context.control_handler.call_action(
            RuntimeToLangBotAction.GET_PLUGIN_SETTINGS,
            {
                "plugin_author": plugin_container.manifest.metadata.author,
                "plugin_name": plugin_container.manifest.metadata.name,
            },
        )

        print("initialize plugin with plugin_settings", plugin_settings)

        # initialize plugin
        await handler.initialize_plugin(plugin_settings)

        # get plugin container from plugin
        plugin_container = runtime_plugin_container.PluginContainer.from_dict(
            await handler.get_plugin_container()
        )

        plugin_container._runtime_plugin_handler = handler

        print("register_plugin", plugin_container)

        self.plugins.append(plugin_container)
        
    async def remove_plugin(
        self,
        plugin_container: runtime_plugin_container.PluginContainer,
    ):
        if plugin_container._runtime_plugin_handler is not None:
            await self.remove_plugin_handler(plugin_container._runtime_plugin_handler)

        self.plugins.remove(plugin_container)

    async def emit_event(self, event_context: EventContext) -> tuple[list[runtime_plugin_container.PluginContainer], EventContext]:
        emitted_plugins: list[runtime_plugin_container.PluginContainer] = []

        for plugin in self.plugins:

            if plugin.status != runtime_plugin_container.RuntimeContainerStatus.INITIALIZED:
                continue

            if not plugin.enabled:
                continue

            if plugin._runtime_plugin_handler is None:
                continue

            resp = await plugin._runtime_plugin_handler.emit_event(event_context.model_dump())

            if resp["emitted"]:
                emitted_plugins.append(plugin)

            emitted_plugins.append(plugin)

            event_context = EventContext.parse_from_dict(resp["event_context"])

            if event_context.is_prevented_postorder():
                break

        for key in event_context.return_value.keys():
            if hasattr(event_context.event, key):
                setattr(event_context.event, key, event_context.get_return_value(key))

        return emitted_plugins, event_context

    async def list_tools(self) -> list[ComponentManifest]:
        tools: list[ComponentManifest] = []
        
        for plugin in self.plugins:
            for component in plugin.components:
                if component.manifest.kind == Tool.__kind__:
                    tools.append(component.manifest)

        return tools

    async def call_tool(self, tool_name: str, tool_parameters: dict[str, typing.Any]) -> dict[str, typing.Any]:
        for plugin in self.plugins:
            for component in plugin.components:
                if component.manifest.kind == Tool.__kind__:
                    if component.manifest.metadata.name != tool_name:
                        continue
                    
                    if plugin._runtime_plugin_handler is None:
                        continue
                    
                    resp = await plugin._runtime_plugin_handler.call_tool(tool_name, tool_parameters)

                    return resp["tool_response"]
        
        return {}
