from __future__ import annotations

import abc
from typing import Any

from langbot_plugin.api.definition.components.base import BaseComponent


class Page(BaseComponent):
    """The page component.

    Each Page component provides a visual page in the LangBot WebUI sidebar
    and can handle API calls from the frontend via ``handle_api``.
    """

    __kind__ = "Page"

    async def handle_api(
        self,
        endpoint: str,
        method: str,
        body: Any = None,
    ) -> Any:
        """Handle an API call from the page frontend.

        Override this method to implement a backend for your page.

        Args:
            endpoint: The API endpoint path (e.g. ``'/entries'``).
            method:   HTTP method (``GET``, ``POST``, ``PUT``, ``DELETE``).
            body:     Request body (parsed JSON, or ``None``).

        Returns:
            Any JSON-serializable data to send back to the page.
        """
        return None
