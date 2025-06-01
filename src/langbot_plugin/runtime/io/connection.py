from __future__ import annotations

import abc


class Connection(abc.ABC):
    """The abstract base class for all connections."""

    @abc.abstractmethod
    async def send(self, message: str) -> None:
        pass

    @abc.abstractmethod
    async def receive(self) -> str:
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        pass
