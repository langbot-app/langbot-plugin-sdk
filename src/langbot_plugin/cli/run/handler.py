from __future__ import annotations

import typing

from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.runtime.plugin.container import PluginContainer
from langbot_plugin.runtime.io.handler import Handler


class PluginRuntimeHandler(Handler):
    """The handler for running plugins."""

    plugin_container: PluginContainer
    
    def __init__(self, connection: connection.Connection):
        super().__init__(connection)

        @self.action("get_plugin_container")
        async def get_plugin_container(data: dict[str, typing.Any]) -> ActionResponse:
            return ActionResponse.success(self.plugin_container.model_dump())
    
    async def get_plugin_settings(self) -> dict[str, typing.Any]:

        resp = await self.call_action(
            "get_plugin_settings",
            {
                "plugin_author": self.plugin_container.manifest.metadata.author,
                "plugin_name": self.plugin_container.manifest.metadata.name,
            }
        )

        return resp

# {"action": "get_plugin_container", "data": {}, "seq_id": 1}