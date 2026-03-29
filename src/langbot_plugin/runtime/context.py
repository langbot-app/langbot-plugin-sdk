from __future__ import annotations

from langbot_plugin.runtime.io.controllers.stdio import (
    server as stdio_controller_server,
)
from langbot_plugin.runtime.io.controllers.ws import server as ws_controller_server
from langbot_plugin.runtime.io.handlers import control as control_handler_cls
from langbot_plugin.runtime.plugin import mgr as plugin_mgr_cls


class RuntimeContext:
    """This class stores the shared context of langbot plugin runtime, for resolving recursive dependencies.

    This module (should) not depend on any other implementation modules.
    """

    stdio_server: stdio_controller_server.StdioServerController | None = (
        None  # stdio control server
    )
    ws_control_server: ws_controller_server.WebSocketServerController | None = (
        None  # ws control
    )
    ws_debug_server: ws_controller_server.WebSocketServerController | None = (
        None  # ws debug server
    )

    control_handler: control_handler_cls.ControlConnectionHandler

    plugin_mgr: plugin_mgr_cls.PluginManager

    ws_debug_port: int = 5401  # Default debug port
