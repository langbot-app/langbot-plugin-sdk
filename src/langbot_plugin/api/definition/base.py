from __future__ import annotations

import abc


class BasePlugin(abc.ABC):
    """The base class for all plugins."""

    def __init__(self, name: str):
        self.name = name

    async def initialize(self) -> None:
        pass

    def __del__(self) -> None:
        pass
