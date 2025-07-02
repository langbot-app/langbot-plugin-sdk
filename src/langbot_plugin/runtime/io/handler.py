from __future__ import annotations

import abc
import asyncio
import json
from typing import Callable, Any, Dict, Awaitable, Coroutine
import traceback

import pydantic

from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.req import ActionRequest
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.entities.io.errors import (
    ConnectionClosedError,
    ActionCallTimeoutError,
    ActionCallError,
)
from langbot_plugin.entities.io.actions.enums import ActionType


class Handler(abc.ABC):
    """The abstract base class for all handlers."""

    conn: connection.Connection

    actions: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]]

    resp_waiters: dict[int, asyncio.Future[ActionResponse]] = {}

    seq_id_index: int = 0

    _disconnect_callback: Callable[[Handler], Coroutine[Any, Any, bool]] | None

    def __init__(
        self,
        connection: connection.Connection,
        disconnect_callback: Callable[[Handler], Coroutine[Any, Any, bool]]
        | None = None,
    ):
        self.conn = connection
        self.actions = {}

        self._disconnect_callback = disconnect_callback

    async def run(self) -> None:
        while True:
            message = None
            try:
                message = await self.conn.receive()
            except ConnectionClosedError:
                if self._disconnect_callback is not None:
                    reconnected = await self._disconnect_callback(self)
                    if reconnected:
                        continue
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
                        traceback.print_exc()
                        error_response = ActionResponse.error(
                            f"{e.__class__.__name__}: {str(e)}"
                        )
                        error_response.seq_id = seq_id
                        await self.conn.send(json.dumps(error_response.model_dump()))

                elif "code" in req_data:  # action response from peer
                    if seq_id in self.resp_waiters:
                        if req_data["code"] != 0:
                            error_response = ActionResponse.error(req_data["message"])
                            error_response.seq_id = seq_id
                            self.resp_waiters[seq_id].set_result(error_response)
                        else:
                            response = ActionResponse.success(req_data["data"])
                            response.seq_id = seq_id
                            response.code = req_data["code"]
                            self.resp_waiters[seq_id].set_result(response)

                        del self.resp_waiters[seq_id]

            asyncio.create_task(handle_message(message))

    async def call_action(
        self, action: ActionType, data: dict[str, Any], timeout: float = 10.0
    ) -> dict[str, Any]:
        """Actively call an action provided by the peer, and wait for the response."""
        self.seq_id_index += 1
        request = ActionRequest.make_request(self.seq_id_index, action.value, data)
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
            raise ActionCallTimeoutError(f"Action {action.value} call timed out")
        except Exception as e:
            raise ActionCallError(f"{e.__class__.__name__}: {str(e)}")

    # decorator to register an action
    def action(
        self, name: ActionType
    ) -> Callable[
        [Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]],
        Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]],
    ]:
        def decorator(
            func: Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]],
        ) -> Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]:
            self.actions[name.value] = func
            return func

        return decorator
