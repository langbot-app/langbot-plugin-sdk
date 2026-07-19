from __future__ import annotations

import argparse
from enum import Enum
import hmac
import logging
import os
import secrets
from collections.abc import Mapping

import asyncio
import contextlib

from langbot_plugin.runtime.io.controllers.stdio import (
    server as stdio_controller_server,
)
from langbot_plugin.runtime.io.controllers.ws import server as ws_controller_server
from langbot_plugin.runtime.io.handlers import control as control_handler_cls
from langbot_plugin.runtime.io.handlers import plugin as plugin_handler_cls
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.plugin import mgr as plugin_mgr_cls
from langbot_plugin.runtime import context
from langbot_plugin.runtime.settings import settings
from langbot_plugin.runtime.security import (
    PLUGIN_DEBUG_KEY_HEADER,
    PLUGIN_REGISTRATION_CAPABILITY_HEADER,
    PLUGIN_RUNTIME_CONTROL_TOKEN_ENV,
    PLUGIN_RUNTIME_CONTROL_TOKEN_HEADER,
    validate_runtime_secret,
)
from langbot_plugin.utils.log import configure_process_logging

logger = logging.getLogger(__name__)


class ControlConnectionMode(Enum):
    STDIO = "stdio"
    WS = "ws"


class RuntimeApplication:
    """Runtime application context."""

    _control_connection_mode: ControlConnectionMode

    context: context.RuntimeContext

    def __init__(self, args: argparse.Namespace):
        self.args = args
        if getattr(args, "pypi_index_url", ""):
            os.environ["LANGBOT_PLUGIN_PYPI_INDEX_URL"] = args.pypi_index_url
        if getattr(args, "pypi_trusted_host", ""):
            os.environ["LANGBOT_PLUGIN_PYPI_TRUSTED_HOST"] = args.pypi_trusted_host
        self.context = context.RuntimeContext()
        self._server_tasks: set[asyncio.Task] = set()
        self._control_tasks: set[asyncio.Task] = set()
        self._control_handler_lock = asyncio.Lock()
        self._closing = False
        self._shutdown_complete = False

        logger.info(f"settings.cloud_service_url: {settings.cloud_service_url}")

        # Set the debug port in context so PluginManager can use it
        self.context.ws_debug_port = self.args.ws_debug_port

        self.context.plugin_mgr = plugin_mgr_cls.PluginManager(self.context)

        if args.stdio_control:
            self._control_connection_mode = ControlConnectionMode.STDIO
        else:
            self._control_connection_mode = ControlConnectionMode.WS

        configured_debug_key = str(settings.plugin_debug_key or "").strip()
        if configured_debug_key:
            settings.plugin_debug_key = validate_runtime_secret(
                configured_debug_key,
                name="PLUGIN_DEBUG_KEY",
            )
        else:
            # Debug access is enabled by default for development, but never
            # with the historical empty-key bypass. The authenticated control
            # channel is the only place where this generated key is exposed.
            settings.plugin_debug_key = secrets.token_urlsafe(48)

        # build controllers layer
        if self._control_connection_mode == ControlConnectionMode.STDIO:
            self.context.stdio_server = stdio_controller_server.StdioServerController()

        elif self._control_connection_mode == ControlConnectionMode.WS:
            control_token = validate_runtime_secret(
                os.environ.get(PLUGIN_RUNTIME_CONTROL_TOKEN_ENV, ""),
                name=PLUGIN_RUNTIME_CONTROL_TOKEN_ENV,
            )
            self.context.ws_control_server = (
                ws_controller_server.WebSocketServerController(
                    self.args.ws_control_port,
                    expected_headers={
                        PLUGIN_RUNTIME_CONTROL_TOKEN_HEADER: control_token,
                    },
                )
            )

        # The plugin WebSocket serves explicit debug clients and Windows
        # Runtime-managed children, with separate authentication credentials.
        self.context.ws_debug_server = ws_controller_server.WebSocketServerController(
            self.args.ws_debug_port,
            request_authenticator=self._authenticate_plugin_request,
        )

    def _authenticate_plugin_request(self, headers: Mapping[str, str]) -> bool:
        """Admit explicit debug clients or one pending installed plugin."""

        supplied_debug_key = str(headers.get(PLUGIN_DEBUG_KEY_HEADER) or "")
        if supplied_debug_key and hmac.compare_digest(
            settings.plugin_debug_key,
            supplied_debug_key,
        ):
            return True

        registration_capability = str(
            headers.get(PLUGIN_REGISTRATION_CAPABILITY_HEADER) or ""
        )
        return self.context.plugin_mgr.is_registration_capability_pending(
            registration_capability
        )

    def set_control_handler(
        self, handler: control_handler_cls.ControlConnectionHandler
    ):
        previous = self.context.activate_control_handler(handler)
        if previous is not None and previous is not handler:
            previous.invalidate()

        async def run_active_handler():
            close_task = None
            if previous is not None and previous is not handler:
                close_task = asyncio.create_task(previous.conn.close())
            try:
                await handler.run()
            finally:
                if close_task is not None:
                    try:
                        await close_task
                    except Exception:
                        logger.warning(
                            "Failed to close superseded control connection",
                            exc_info=True,
                        )

        task = asyncio.create_task(run_active_handler())
        logger.info("Got control connection.")
        return task

    def _control_task_done(self, task: asyncio.Task) -> None:
        self._control_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Control connection task failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def run(self):
        server_coroutines = []

        # ==== control server ====
        async def new_control_connection_callback(connection: Connection):
            handler = control_handler_cls.ControlConnectionHandler(
                connection, self.context
            )
            await self.set_control_handler(handler)

        if self.context.stdio_server:
            server_coroutines.append(
                self.context.stdio_server.run(new_control_connection_callback)
            )

        if self.context.ws_control_server:
            server_coroutines.append(
                self.context.ws_control_server.run(new_control_connection_callback)
            )

        # ==== plugin debug server ====
        async def new_plugin_debug_connection_callback(connection: Connection):
            plugin_handler = plugin_handler_cls.PluginConnectionHandler(
                connection, self.context, debug_plugin=True
            )

            await self.context.plugin_mgr.add_plugin_handler(plugin_handler)

        if self.context.ws_debug_server:
            server_coroutines.append(
                self.context.ws_debug_server.run(new_plugin_debug_connection_callback)
            )

        # Schedule listeners before dependency reconciliation. A slow package
        # index must not make the control ports look dead.
        for coroutine in server_coroutines:
            task = asyncio.create_task(coroutine)
            self._server_tasks.add(task)
        await asyncio.sleep(0)
        for task in list(self._server_tasks):
            if task.done() and not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    raise exc

        # ==== check and install dependencies for all plugins ====
        if not self.args.skip_deps_check:
            logger.info("Ensuring all installed plugins dependencies are installed...")
            await self.context.plugin_mgr.ensure_all_plugins_dependencies_installed()

        # ==== launch plugin processes ====
        if not self.args.debug_only:
            task = asyncio.create_task(self.context.plugin_mgr.launch_all_plugins())
            self._server_tasks.add(task)

        if self._server_tasks:
            await asyncio.gather(*list(self._server_tasks))

    async def shutdown(self):
        if self._shutdown_complete:
            return
        self._closing = True

        async with self._control_handler_lock:
            control_handler = getattr(self.context, "control_handler", None)
            if control_handler is not None:
                close = getattr(control_handler, "close", None)
                if close is not None:
                    with contextlib.suppress(Exception):
                        await close()

        await self.context.plugin_mgr.shutdown_all_plugins()

        tasks = [*self._control_tasks, *self._server_tasks]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._control_tasks.clear()
        self._server_tasks.clear()
        self._shutdown_complete = True


def main(args: argparse.Namespace):
    configure_process_logging()

    app = RuntimeApplication(args)

    async def run_with_shutdown() -> None:
        try:
            await app.run()
        finally:
            await app.shutdown()

    try:
        asyncio.run(run_with_shutdown())
    except asyncio.CancelledError:
        logger.info("Runtime application cancelled")
        return
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, exiting...")
        return
