from __future__ import annotations

import abc
import typing

from langbot_plugin.api.proxies import langbot_api


class BasePlugin(abc.ABC, langbot_api.LangBotAPIProxy):
    """The base class for all plugins."""

    config: dict[str, typing.Any]

    def get_config(self) -> dict[str, typing.Any]:
        """Get the config of the plugin."""
        return self.config

    def __init__(self):
        pass

    async def initialize(self) -> None:
        pass

    def __del__(self) -> None:
        pass


class NonePlugin(BasePlugin):
    """The plugin that does nothing, just acts as a placeholder."""

    def __init__(self):
        super().__init__()
