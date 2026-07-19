from __future__ import annotations

import asyncio

from langbot_plugin.runtime.io.controllers.stdio import (
    server as stdio_controller_server,
)
from langbot_plugin.runtime.io.controllers.ws import server as ws_controller_server
from langbot_plugin.runtime.io.handlers import control as control_handler_cls
from langbot_plugin.runtime.plugin import mgr as plugin_mgr_cls
from langbot_plugin.entities.io.context import ActionContext


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

    workspace_binding: ActionContext | None = None
    """Trusted, immutable Workspace binding for this Runtime worker."""

    ws_debug_port: int = 5401  # Default debug port

    def __init__(self):
        self.workspace_binding = None
        self._workspace_binding_ready = asyncio.Event()

    def bind_workspace(
        self,
        action_context: ActionContext | dict,
    ) -> ActionContext:
        """Bind this Runtime worker to one Workspace and placement generation."""

        binding = ActionContext.model_validate(action_context).without_installation()
        if self.workspace_binding is not None and self.workspace_binding != binding:
            raise ValueError("Plugin Runtime cannot be rebound to another Workspace")
        self.workspace_binding = binding
        self._workspace_binding_ready.set()
        return binding

    async def wait_for_workspace_binding(self) -> ActionContext:
        """Wait until LangBot has supplied the trusted Runtime binding."""

        await self._workspace_binding_ready.wait()
        if self.workspace_binding is None:  # pragma: no cover - Event invariant
            raise RuntimeError("Plugin Runtime Workspace binding is unavailable")
        return self.workspace_binding
