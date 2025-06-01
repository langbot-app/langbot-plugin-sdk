# handle connection from LangBot
from __future__ import annotations

from typing import Any

from langbot_plugin.runtime.io import handler, connection


class ControlConnectionHandler(handler.Handler):
    """The handler for control connection."""

    def __init__(self, connection: connection.Connection):
        super().__init__(connection)

        @self.action("ping")
        async def ping(data: dict[str, Any]) -> handler.ActionResponse:
            resp = await self.call_action("ping", {}, 10)
            print("received resp: ", resp)
            return handler.ActionResponse.success({"message": "pong"})


# {"action": "ping", "data": {}, "seq_id": 1}
# {"code": 0, "message": "ok", "data": {"msg": "hello"}, "seq_id": 1}
