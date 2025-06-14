# handle connection from LangBot
from __future__ import annotations

from typing import Any

from langbot_plugin.runtime.io import handler, connection
from langbot_plugin.entities.io.actions.enums import (
    CommonAction,
    LangBotToRuntimeAction,
)
from langbot_plugin.runtime import context as context_module


class ControlConnectionHandler(handler.Handler):
    """The handler for control connection."""

    context: context_module.RuntimeContext

    def __init__(
        self, connection: connection.Connection, context: context_module.RuntimeContext
    ):
        super().__init__(connection)
        self.context = context

        @self.action(CommonAction.PING)
        async def ping(data: dict[str, Any]) -> handler.ActionResponse:
            return handler.ActionResponse.success({"message": "pong"})

        @self.action(LangBotToRuntimeAction.LIST_PLUGINS)
        async def list_plugins(data: dict[str, Any]) -> handler.ActionResponse:
            return handler.ActionResponse.success(
                {
                    "plugins": [
                        plugin.model_dump()
                        for plugin in self.context.plugin_mgr.plugins
                    ]
                }
            )

        @self.action(LangBotToRuntimeAction.INSTALL_PLUGIN)
        async def install_plugin(data: dict[str, Any]) -> handler.ActionResponse:
            return handler.ActionResponse.success({"message": "installing plugin"})

        @self.action(LangBotToRuntimeAction.EMIT_EVENT)
        async def emit_event(data: dict[str, Any]) -> handler.ActionResponse:
            return handler.ActionResponse.success({})


# {"action": "ping", "data": {}, "seq_id": 1}
# {"code": 0, "message": "ok", "data": {"msg": "hello"}, "seq_id": 1}
