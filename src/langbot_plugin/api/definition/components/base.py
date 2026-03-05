from __future__ import annotations

import abc

from langbot_plugin.api.definition.plugin import BasePlugin


class BaseComponent(abc.ABC):
    """The abstract base class for all components."""

    plugin: BasePlugin

    def __init__(self):
        pass

    async def initialize(self) -> None:
        pass


class NoneComponent(BaseComponent):
    """The component that does nothing, just acts as a placeholder."""

    def __init__(self):
        super().__init__()

    async def initialize(self) -> None:
        pass
