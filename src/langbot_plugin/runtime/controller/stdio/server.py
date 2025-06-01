# Stdio server for LangBot control connection
from __future__ import annotations

from langbot_plugin.runtime.io.connections import stdio as stdio_connection
from langbot_plugin.runtime.io.handlers import control as control_handler
from langbot_plugin.runtime.io import handler as io_handler


class StdioServer:
    def __init__(self, handler_manager: io_handler.HandlerManager):
        self.handler_manager = handler_manager

    async def run(self):
        print("Starting Stdio server")
        connection = stdio_connection.StdioConnection()
        handler = control_handler.ControlConnectionHandler(connection)
        task = self.handler_manager.set_control_handler(handler)
        await task
