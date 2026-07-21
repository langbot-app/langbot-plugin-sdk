from __future__ import annotations

import argparse
from enum import Enum
import logging
import os

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

        # build controllers layer
        if self._control_connection_mode == ControlConnectionMode.STDIO:
            self.context.stdio_server = stdio_controller_server.StdioServerController()

        elif self._control_connection_mode == ControlConnectionMode.WS:
            self.context.ws_control_server = (
                ws_controller_server.WebSocketServerController(
                    self.args.ws_control_port
                )
            )

        # enable debugging ws server
        self.context.ws_debug_server = ws_controller_server.WebSocketServerController(
            self.args.ws_debug_port
        )

    def set_control_handler(
        self, handler: control_handler_cls.ControlConnectionHandler
    ):
        async def run_current_generation() -> None:
            previous = getattr(self.context, "control_handler", None)
            if previous is not None and previous is not handler:
                close = getattr(previous, "close", None)
                if close is not None:
                    await close()

            if self._closing:
                close = getattr(handler, "close", None)
                if close is not None:
                    await close()
                return

            self.context.control_handler = handler
            logger.info("Got control connection.")
            mark_ready = getattr(
                self.context.plugin_mgr, "mark_control_connection_ready", None
            )
            if mark_ready is not None:
                mark_ready()
            waiter = self.context.plugin_mgr.wait_for_control_connection
            if waiter is not None:
                if not waiter.done():
                    waiter.set_result(None)
                # Installed plugins are launched only once. Later control
                # generations reuse the existing supervised plugin processes.
                self.context.plugin_mgr.wait_for_control_connection = None
            await handler.run()

        task = asyncio.create_task(run_current_generation())
        self._control_tasks.add(task)
        task.add_done_callback(self._control_task_done)
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
