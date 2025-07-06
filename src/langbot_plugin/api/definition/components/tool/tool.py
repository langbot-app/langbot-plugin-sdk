from __future__ import annotations

import abc
from typing import Any

from langbot_plugin.api.definition.components.base import BaseComponent


class Tool(BaseComponent):
    """The tool component."""

    __kind__ = "Tool"

    @abc.abstractmethod
    async def call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Call the tool."""
        pass
