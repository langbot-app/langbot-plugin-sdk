from __future__ import annotations

import abc
import typing


class BasePlugin(abc.ABC):
    """The base class for all plugins."""

    config: dict[str, typing.Any]

    def __init__(self):
        pass

    async def initialize(self) -> None:
        pass

    def __del__(self) -> None:
        pass


class NonePlugin(BasePlugin):
    """The plugin that does nothing."""

    def __init__(self):
        super().__init__()
