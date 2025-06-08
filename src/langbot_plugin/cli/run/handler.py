from __future__ import annotations

import typing
from copy import deepcopy

from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.runtime.plugin.container import PluginContainer
from langbot_plugin.runtime.io.handler import Handler
from langbot_plugin.api.entities import events, context
from langbot_plugin.api.definition.components.common.event_listener import EventListener


class PluginRuntimeHandler(Handler):
    """The handler for running plugins."""

    plugin_container: PluginContainer
    
    def __init__(self, connection: connection.Connection):
        super().__init__(connection)

        @self.action("get_plugin_container")
        async def get_plugin_container(data: dict[str, typing.Any]) -> ActionResponse:
            return ActionResponse.success(self.plugin_container.model_dump())

        @self.action("emit_event")
        async def emit_event(data: dict[str, typing.Any]) -> ActionResponse:
            """Emit an event to the plugin.
            
            {
                "event_context": dict[str, typing.Any],
            }
            """

            event_name = data["event_context"]["event_name"]

            if getattr(events, event_name) is None:
                return ActionResponse.error(f"Event {event_name} not found")
            
            event_class = getattr(events, event_name)
            assert isinstance(event_class, type(events.BaseEventModel))
            event_instance = event_class(**data["event_context"]["event"])

            args = deepcopy(data["event_context"])
            args["event"] = event_instance
            
            event_context = context.EventContext(
                **args,
            )

            # check if the event is registered
            for component in self.plugin_container.components:
                if component.manifest.kind == "EventListener":
                    if component.component_instance is None:
                        return ActionResponse.error(f"Event listener is not initialized")
                    
                    assert isinstance(component.component_instance, EventListener)

                    for handler in component.component_instance.registered_handlers[event_class]:
                        await handler(event_context)

                    break
            
            return ActionResponse.success(data={
                "event_context": event_context.model_dump(),
            })
            

    async def get_plugin_settings(self) -> dict[str, typing.Any]:

        resp = await self.call_action(
            "get_plugin_settings",
            {
                "plugin_author": self.plugin_container.manifest.metadata.author,
                "plugin_name": self.plugin_container.manifest.metadata.name,
            }
        )

        return resp

# {"action": "get_plugin_container", "data": {}, "seq_id": 1}