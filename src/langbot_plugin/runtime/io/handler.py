from __future__ import annotations

import abc
import asyncio
import json
from typing import Callable, Any, Dict, Awaitable, Coroutine

import pydantic

from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.req import ActionRequest
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.entities.io.errors import (
    ConnectionClosedError,
    ActionCallTimeoutError,
    ActionCallError,
)


class Handler(abc.ABC):
    """The abstract base class for all handlers."""

    conn: connection.Connection

    actions: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]]

    resp_waiters: dict[int, asyncio.Future[ActionResponse]] = {}

    seq_id_index: int = 0

    def __init__(self, connection: connection.Connection):
        self.conn = connection
        self.actions = {}

    async def run(self) -> None:
        while True:
            message = None
            try:
                message = await self.conn.receive()
            except ConnectionClosedError:
                print("Connection closed")
                break
            if message is None:
                continue

            async def handle_message(message: str):
                # sh*t, i dont really know how to use generic type here
                # so just use dict[str, Any] for now
                req_data = json.loads(message)
                seq_id = req_data["seq_id"] if "seq_id" in req_data else -1

                if "action" in req_data:  # action request from peer
                    try:
                        if req_data["action"] not in self.actions:
                            raise ValueError(f"Action {req_data['action']} not found")

                        response = await self.actions[req_data["action"]](
                            req_data["data"]
                        )
                        response.seq_id = seq_id
                        await self.conn.send(json.dumps(response.model_dump()))
                    except Exception as e:
                        error_response = ActionResponse.error(
                            f"{e.__class__.__name__}: {str(e)}"
                        )
                        error_response.seq_id = seq_id
                        await self.conn.send(json.dumps(error_response.model_dump()))

                elif "code" in req_data:  # action response from peer
                    if seq_id in self.resp_waiters:
                        response = ActionResponse.success(req_data["data"])
                        response.seq_id = seq_id
                        self.resp_waiters[seq_id].set_result(response)
                        del self.resp_waiters[seq_id]

            asyncio.create_task(handle_message(message))

    async def call_action(
        self, action: str, data: dict[str, Any], timeout: float = 10.0
    ) -> dict[str, Any]:
        """Actively call an action provided by the peer, and wait for the response."""
        self.seq_id_index += 1
        request = ActionRequest.make_request(self.seq_id_index, action, data)
        await self.conn.send(json.dumps(request.model_dump()))
        # wait for response
        future = asyncio.Future[ActionResponse]()
        self.resp_waiters[self.seq_id_index] = future
        try:
            response = await asyncio.wait_for(future, timeout)
            if response.code != 0:
                raise ActionCallError(f"{response.message}")
            return response.data
        except asyncio.TimeoutError:
            raise ActionCallTimeoutError(f"Action {action} call timed out")
        except Exception as e:
            raise ActionCallError(f"{e.__class__.__name__}: {str(e)}")

    # decorator to register an action
    def action(
        self, name: str
    ) -> Callable[
        [Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]],
        Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]],
    ]:
        def decorator(
            func: Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]],
        ) -> Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]:
            self.actions[name] = func
            return func

        return decorator


class HandlerManager:
    """The manager for handlers."""

    control_handler: Handler
    plugin_handlers: dict[str, Handler]

    def __init__(self):
        self.langbot_handler = None
        self.plugin_handlers = {}

    def set_control_handler(self, handler: Handler) -> asyncio.Task:
        self.control_handler = handler
        return asyncio.create_task(handler.run())

    def set_plugin_handler(self, name: str, handler: Handler) -> None:
        self.plugin_handlers[name] = handler
