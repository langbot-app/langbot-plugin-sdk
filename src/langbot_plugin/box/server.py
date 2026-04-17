"""Standalone Box Runtime service exposing BoxRuntime via action RPC.

Usage (stdio, launched by LangBot as subprocess):
    python -m langbot_plugin.box.server

Usage (ws, for remote/docker mode):
    python -m langbot_plugin.box.server --mode ws --port 5410

All WebSocket endpoints share a single port (default 5410):
    /rpc/ws                                         — Action RPC (control channel)
    /v1/sessions/{session_id}/managed-process/ws    — Managed process stdio relay
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import sys
from typing import Any

import pydantic
from aiohttp import web

from langbot_plugin.entities.io.actions.enums import CommonAction
from langbot_plugin.entities.io.errors import ConnectionClosedError
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.handler import Handler
from langbot_plugin.utils.log import configure_process_logging

from .actions import LangBotToBoxAction
from .errors import (
    BoxManagedProcessConflictError,
    BoxManagedProcessNotFoundError,
    BoxSessionNotFoundError,
)
from .models import BoxExecutionResult, BoxManagedProcessSpec, BoxSpec
from .runtime import BoxRuntime

logger = logging.getLogger('langbot.box.server')


def _result_to_dict(result: BoxExecutionResult) -> dict:
    return result.model_dump(mode='json')


# ── aiohttp WebSocket → Connection adapter ───────────────────────────


class AiohttpWSConnection(Connection):
    """Adapt an aiohttp ``WebSocketResponse`` to the SDK ``Connection`` interface.

    This allows ``BoxServerHandler`` (and therefore ``Handler``) to work over
    an aiohttp WebSocket without any changes to the handler/IO layer.
    """

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self._ws = ws
        self._send_lock = asyncio.Lock()

    async def send(self, message: str) -> None:
        async with self._send_lock:
            try:
                await self._ws.send_str(message)
            except ConnectionResetError:
                raise ConnectionClosedError('Connection closed during send')

    async def receive(self) -> str:
        msg = await self._ws.receive()
        if msg.type == web.WSMsgType.TEXT:
            return msg.data
        if msg.type in (
            web.WSMsgType.CLOSE,
            web.WSMsgType.CLOSING,
            web.WSMsgType.CLOSED,
            web.WSMsgType.ERROR,
        ):
            raise ConnectionClosedError('Connection closed')
        raise ConnectionClosedError(f'Unexpected message type: {msg.type}')

    async def close(self) -> None:
        await self._ws.close()


# ── BoxServerHandler ─────────────────────────────────────────────────


class BoxServerHandler(Handler):
    """Server-side handler that registers box actions backed by BoxRuntime."""

    name = 'BoxServerHandler'

    def __init__(self, connection: Connection, runtime: BoxRuntime):
        super().__init__(connection)
        self._runtime = runtime
        self._register_actions()

    def _register_actions(self) -> None:
        @self.action(CommonAction.PING)
        async def ping(data: dict[str, Any]) -> ActionResponse:
            return ActionResponse.success({})

        @self.action(LangBotToBoxAction.HEALTH)
        async def health(data: dict[str, Any]) -> ActionResponse:
            info = await self._runtime.get_backend_info()
            return ActionResponse.success(info)

        @self.action(LangBotToBoxAction.STATUS)
        async def status(data: dict[str, Any]) -> ActionResponse:
            result = await self._runtime.get_status()
            return ActionResponse.success(result)

        @self.action(LangBotToBoxAction.EXEC)
        async def exec_cmd(data: dict[str, Any]) -> ActionResponse:
            try:
                spec = BoxSpec.model_validate(data)
            except pydantic.ValidationError as exc:
                return ActionResponse.error(f'BoxValidationError: {exc}')
            result = await self._runtime.execute(spec)
            return ActionResponse.success(_result_to_dict(result))

        @self.action(LangBotToBoxAction.CREATE_SESSION)
        async def create_session(data: dict[str, Any]) -> ActionResponse:
            try:
                spec = BoxSpec.model_validate(data)
            except pydantic.ValidationError as exc:
                return ActionResponse.error(f'BoxValidationError: {exc}')
            info = await self._runtime.create_session(spec)
            return ActionResponse.success(info)

        @self.action(LangBotToBoxAction.GET_SESSION)
        async def get_session(data: dict[str, Any]) -> ActionResponse:
            return ActionResponse.success(self._runtime.get_session(data['session_id']))

        @self.action(LangBotToBoxAction.GET_SESSIONS)
        async def get_sessions(data: dict[str, Any]) -> ActionResponse:
            return ActionResponse.success({'sessions': self._runtime.get_sessions()})

        @self.action(LangBotToBoxAction.DELETE_SESSION)
        async def delete_session(data: dict[str, Any]) -> ActionResponse:
            await self._runtime.delete_session(data['session_id'])
            return ActionResponse.success({'deleted': data['session_id']})

        @self.action(LangBotToBoxAction.START_MANAGED_PROCESS)
        async def start_managed_process(data: dict[str, Any]) -> ActionResponse:
            session_id = data['session_id']
            try:
                spec = BoxManagedProcessSpec.model_validate(data['spec'])
            except pydantic.ValidationError as exc:
                return ActionResponse.error(f'BoxValidationError: {exc}')
            info = await self._runtime.start_managed_process(session_id, spec)
            return ActionResponse.success(info)

        @self.action(LangBotToBoxAction.GET_MANAGED_PROCESS)
        async def get_managed_process(data: dict[str, Any]) -> ActionResponse:
            return ActionResponse.success(self._runtime.get_managed_process(data['session_id']))

        @self.action(LangBotToBoxAction.GET_BACKEND_INFO)
        async def get_backend_info(data: dict[str, Any]) -> ActionResponse:
            info = await self._runtime.get_backend_info()
            return ActionResponse.success(info)

        @self.action(LangBotToBoxAction.SHUTDOWN)
        async def shutdown(data: dict[str, Any]) -> ActionResponse:
            await self._runtime.shutdown()
            return ActionResponse.success({})


# ── Managed process WebSocket relay ──────────────────────────────────


def _error_response(exc: Exception) -> web.Response:
    return web.json_response(
        {'error': {'code': type(exc).__name__, 'message': str(exc)}},
        status=400,
    )


async def handle_managed_process_ws(request: web.Request) -> web.StreamResponse:
    runtime: BoxRuntime = request.app['runtime']
    session_id = request.match_info['session_id']

    runtime_session = runtime._sessions.get(session_id)
    if runtime_session is None:
        return _error_response(BoxSessionNotFoundError(f'session {session_id} not found'))

    managed_process = runtime_session.managed_process
    if managed_process is None:
        return _error_response(BoxManagedProcessNotFoundError(f'session {session_id} has no managed process'))
    if not managed_process.is_running:
        return _error_response(
            BoxManagedProcessConflictError(f'managed process in session {session_id} is not running')
        )

    ws = web.WebSocketResponse(protocols=('mcp',))
    await ws.prepare(request)

    async with managed_process.attach_lock:
        process = managed_process.process
        stdout = process.stdout
        stdin = process.stdin
        if stdout is None or stdin is None:
            await ws.close(message=b'managed process stdio unavailable')
            return ws

        async def _stdout_to_ws() -> None:
            while True:
                line = await stdout.readline()
                if not line:
                    break
                await ws.send_str(line.decode('utf-8', errors='replace').rstrip('\n'))
                runtime_session.info.last_used_at = dt.datetime.now(dt.timezone.utc)

        async def _ws_to_stdin() -> None:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    stdin.write((msg.data + '\n').encode('utf-8'))
                    await stdin.drain()
                    runtime_session.info.last_used_at = dt.datetime.now(dt.timezone.utc)
                elif msg.type in (
                    web.WSMsgType.CLOSE,
                    web.WSMsgType.CLOSING,
                    web.WSMsgType.CLOSED,
                    web.WSMsgType.ERROR,
                ):
                    break

        stdout_task = asyncio.create_task(_stdout_to_ws())
        stdin_task = asyncio.create_task(_ws_to_stdin())
        try:
            done, pending = await asyncio.wait(
                [stdout_task, stdin_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        finally:
            await ws.close()

    return ws


# ── Action RPC WebSocket handler ─────────────────────────────────────


async def handle_rpc_ws(request: web.Request) -> web.StreamResponse:
    """Handle action RPC over a single aiohttp WebSocket connection."""
    runtime: BoxRuntime = request.app['runtime']

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    connection = AiohttpWSConnection(ws)
    handler = BoxServerHandler(connection, runtime)
    await handler.run()

    return ws


# ── App factory ──────────────────────────────────────────────────────


def create_app(runtime: BoxRuntime) -> web.Application:
    """Create the aiohttp app with all WebSocket routes on a single port."""
    app = web.Application()
    app['runtime'] = runtime
    app.router.add_get('/rpc/ws', handle_rpc_ws)
    app.router.add_get('/v1/sessions/{session_id}/managed-process/ws', handle_managed_process_ws)
    return app


# ── Entry point ──────────────────────────────────────────────────────


async def _run_server(host: str, port: int, mode: str) -> None:
    runtime = BoxRuntime(logger=logger)
    await runtime.initialize()

    # Start aiohttp — serves managed-process relay and (in ws mode)
    # also the action RPC endpoint, all on the same port.
    runner: web.AppRunner | None = None
    try:
        ws_app = create_app(runtime)
        runner = web.AppRunner(ws_app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f'Box server listening on {host}:{port}')
    except OSError as exc:
        logger.warning(f'Box server failed to bind {host}:{port}: {exc}')
        logger.warning('Managed process WebSocket attach will be unavailable.')

    try:
        if mode == 'stdio':
            from langbot_plugin.runtime.io.controllers.stdio.server import StdioServerController

            async def new_connection_callback(connection: Connection) -> None:
                handler = BoxServerHandler(connection, runtime)
                await handler.run()

            ctrl = StdioServerController()
            await ctrl.run(new_connection_callback)
        else:
            # In ws mode, action RPC is served via aiohttp on /rpc/ws.
            # Keep the server alive until cancelled.
            logger.info(f'Box action RPC available at ws://{host}:{port}/rpc/ws')
            stop_event = asyncio.Event()
            await stop_event.wait()
    finally:
        await runtime.shutdown()
        if runner is not None:
            await runner.cleanup()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='LangBot Box Runtime Service')
    parser.add_argument('--host', default='0.0.0.0', help='Bind address')
    parser.add_argument('--port', type=int, default=5410, help='Bind port')
    parser.add_argument(
        '--mode', choices=['stdio', 'ws'], default='stdio', help='Control channel transport (default: stdio)'
    )
    args = parser.parse_args(argv)

    configure_process_logging(stream=sys.stderr)
    asyncio.run(_run_server(args.host, args.port, args.mode))


if __name__ == '__main__':
    main()
