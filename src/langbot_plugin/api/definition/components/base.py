from __future__ import annotations

import abc
import typing

from langbot_plugin.api.definition.plugin import BasePlugin


class BaseComponent(abc.ABC):
    """The abstract base class for all components."""

    plugin: BasePlugin

    def __init__(self):
        pass

    async def initialize(self) -> None:
        pass


class PolymorphicComponent(BaseComponent):
    """Multi-instance component."""

    instance_id: str
    """The id of running component instance"""

    config: dict[str, typing.Any]
    """Component instance specified configuration"""


class NoneComponent(BaseComponent):
    """The component that does nothing, just acts as a placeholder."""

    def __init__(self):
        super().__init__()

    async def initialize(self) -> None:
        pass
