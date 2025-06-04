from __future__ import annotations

from typing import Callable

import pydantic.v1 as pydantic

from langbot_plugin.api.definition.components.base import BaseComponent
from langbot_plugin.api.entities.events import BaseEventModel
from langbot_plugin.api.entities.context import EventContext


class EventListener(BaseComponent):
    """The event listener component."""

    registered_handlers: dict[
        type[BaseEventModel], list[Callable[[EventContext], None]]
    ] = pydantic.Field(default_factory=dict)

    def handler(
        self,
        event_type: type[BaseEventModel],
    ) -> Callable[[Callable[[EventContext], None]], None]:
        """Register a handler for the event."""
        def decorator(handler: Callable[[EventContext], None]) -> None:
            if event_type not in self.registered_handlers:
                self.registered_handlers[event_type] = []
            self.registered_handlers[event_type].append(handler)
        return decorator
