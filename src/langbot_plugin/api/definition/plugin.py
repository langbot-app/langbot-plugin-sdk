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

    async def handle_page_api(
        self,
        page_id: str,
        endpoint: str,
        method: str,
        body: typing.Any = None,
    ) -> typing.Any:
        """Handle API calls from plugin pages.

        Override this method to implement a backend for your plugin pages.
        All plugin components can call this method.

        Args:
            page_id: The page identifier from manifest.yaml
            endpoint: The API endpoint path requested by the page
            method: HTTP method (GET, POST, PUT, DELETE)
            body: Request body (JSON)

        Returns:
            Response data (will be JSON-serialized)
        """
        return None

    def __del__(self) -> None:
        pass


class NonePlugin(BasePlugin):
    """The plugin that does nothing, just acts as a placeholder."""

    def __init__(self):
        super().__init__()
