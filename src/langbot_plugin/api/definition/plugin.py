from __future__ import annotations

import abc
import typing

from langbot_plugin.api.proxies import langbot_api
from langbot_plugin.api.proxies.invocation import current_binding, current_config


class BasePlugin(abc.ABC, langbot_api.LangBotAPIProxy):
    """The base class for all plugins."""

    _legacy_config: dict[str, typing.Any]

    @property
    def config(self) -> dict[str, typing.Any]:
        """Expose task-local config while preserving dedicated plugin behavior."""

        scoped = current_config(getattr(self, "plugin_runtime_handler", None))
        if scoped is not None:
            return dict(scoped)
        return getattr(self, "_legacy_config", {})

    @config.setter
    def config(self, value: dict[str, typing.Any]) -> None:
        self._legacy_config = dict(value)

    def get_config(self) -> dict[str, typing.Any]:
        """Return the active invocation config, or the legacy dedicated config."""

        return self.config

    def get_installation_binding(self):
        """Return the active certified installation binding, if any."""

        return current_binding(getattr(self, "plugin_runtime_handler", None))

    def __init__(self):
        self._legacy_config = {}

    async def initialize(self) -> None:
        pass

    def __del__(self) -> None:
        pass


class NonePlugin(BasePlugin):
    """The plugin that does nothing, just acts as a placeholder."""

    def __init__(self):
        super().__init__()
