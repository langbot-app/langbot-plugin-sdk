from __future__ import annotations

from typing import Any, Callable, Coroutine

import pydantic
from pydantic import BaseModel

from langbot_plugin.api.definition.components.base import BaseComponent


class Subcommand(BaseModel):
    """The subcommand model."""

    subcommand: Callable[[list[str]], Coroutine[Any, Any, None]]
    """The subcommand function."""
    help: str
    """The help message."""
    usage: str
    """The usage message."""
    aliases: list[str]
    """The aliases of the subcommand."""


class Command(BaseComponent):
    """The command component."""

    __kind__ = "Command"

    registered_subcommands: dict[str, Subcommand] = pydantic.Field(default_factory=dict)

    def __init__(self):
        self.registered_subcommands = {}

    def subcommand(
        self,
        name: str,
        help: str = '',
        usage: str = '',
        aliases: list[str] = [],
    ) -> Callable[[Callable[[list[str]], Coroutine[Any, Any, None]]], Callable[[list[str]], Coroutine[Any, Any, None]]]:
        """Register a subcommand."""

        def decorator(subcommand: Callable[[list[str]], Coroutine[Any, Any, None]]) -> Callable[[list[str]], Coroutine[Any, Any, None]]:
            self.registered_subcommands[name] = Subcommand(
                subcommand=subcommand,
                help=help,
                usage=usage,
                aliases=aliases,
            )
            return subcommand

        return decorator
