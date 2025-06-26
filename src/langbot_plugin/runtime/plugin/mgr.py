from __future__ import annotations

import typing
from langbot_plugin.runtime.plugin import container as runtime_plugin_container
from langbot_plugin.runtime.io.handlers import plugin as runtime_plugin_handler_cls
from langbot_plugin.runtime import context as context_module
from langbot_plugin.api.entities.context import EventContext
from langbot_plugin.api.definition.components.common.event_listener import EventListener


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

    async def register_plugin(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
        container_data: dict[str, typing.Any],
    ):
        plugin_container = runtime_plugin_container.PluginContainer.from_dict(
            container_data
        )
        self.plugins.append(plugin_container)
        print("register_plugin", plugin_container)

    async def emit_event(self, event_context: EventContext) -> tuple[list[runtime_plugin_container.PluginContainer], EventContext]:
        emitted_plugins: list[runtime_plugin_container.PluginContainer] = []

        for plugin in self.plugins:

            if plugin.status != runtime_plugin_container.RuntimeContainerStatus.INITIALIZED:
                continue

            if not plugin.enabled:
                continue

            event_listener_component: runtime_plugin_container.ComponentContainer | None = None

            for component in plugin.components:
                if component.manifest.kind == EventListener.__kind__:
                    event_listener_component = component
                    break

            if event_listener_component is None:
                continue

            # emit event to event listener component
            event_listener_inst = event_listener_component.component_instance
            assert isinstance(event_listener_inst, EventListener)

            if event_context.event.__class__ not in event_listener_inst.registered_handlers:
                continue

            for handler in event_listener_inst.registered_handlers[event_context.event.__class__]:
                await handler(event_context)

            emitted_plugins.append(plugin)

            if event_context.is_prevented_postorder():
                break

        for key in event_context.return_value.keys():
            if hasattr(event_context.event, key):
                setattr(event_context.event, key, event_context.get_return_value(key))

        return emitted_plugins, event_context
