from __future__ import annotations

import abc
import asyncio
import json
from typing import (
    Callable,
    Any,
    Coroutine,
    AsyncGenerator,
    Union,
    AsyncIterator,
)
import traceback
import random

from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.req import ActionRequest
from langbot_plugin.entities.io.resp import ActionResponse, ChunkStatus
from langbot_plugin.entities.io.errors import (
    ConnectionClosedError,
    ActionCallTimeoutError,
    ActionCallError,
)
from langbot_plugin.entities.io.actions.enums import ActionType


class Handler(abc.ABC):
    """The abstract base class for all handlers."""
    name: str = "Handler"

    conn: connection.Connection

    actions: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, ActionResponse]]]

    resp_waiters: dict[int, asyncio.Future[ActionResponse]] = {}
    resp_queues: dict[int, asyncio.Queue[ActionResponse]] = {}

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
        self.seq_id_index = random.randint(0, 100000)
        self.resp_waiters = {}
        self.resp_queues = {}

        self._disconnect_callback = disconnect_callback

    def set_disconnect_callback(
        self,
        disconnect_callback: Callable[[Handler], Coroutine[Any, Any, bool]]
        | None = None,
    ):
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
                # 2025/07/02: i know now, learned from dify-plugin-sdk, but maybe i will implement it later
                req_data = json.loads(message)
                seq_id = req_data["seq_id"] if "seq_id" in req_data else -1

                if "action" in req_data:  # action request from peer

                    try:
                        if req_data["action"] not in self.actions:
                            raise ValueError(f"Action {req_data['action']} not found")

                        response = self.actions[req_data["action"]](req_data["data"])

                        if not isinstance(response, AsyncGenerator):
                            if isinstance(response, Coroutine):
                                response = await response

                            response.seq_id = seq_id
                            await self.conn.send(json.dumps(response.model_dump()))
                        elif isinstance(response, AsyncGenerator):
                            response_generator = response
                            async for chunk in response_generator:
                                assert isinstance(chunk, ActionResponse)
                                chunk.seq_id = seq_id
                                chunk.chunk_status = ChunkStatus.CONTINUE
                                await self.conn.send(json.dumps(chunk.model_dump()))

                            end_response = ActionResponse.success({})
                            end_response.seq_id = seq_id
                            end_response.chunk_status = ChunkStatus.END
                            await self.conn.send(json.dumps(end_response.model_dump()))
                    except Exception as e:
                        traceback.print_exc()
                        error_response = ActionResponse.error(
                            f"{e.__class__.__name__}: {str(e)}"
                        )
                        error_response.seq_id = seq_id
                        await self.conn.send(json.dumps(error_response.model_dump()))

                elif "code" in req_data:  # action response from peer
                    response = ActionResponse.model_validate(req_data)

                    # Handle single response (for call_action)
                    if seq_id in self.resp_waiters:
                        self.resp_waiters[seq_id].set_result(response)

                    # Handle streaming response (for call_action_generator)
                    if seq_id in self.resp_queues:
                        await self.resp_queues[seq_id].put(response)

            asyncio.create_task(handle_message(message))

    async def call_action(
        self, action: ActionType, data: dict[str, Any], timeout: float = 15.0
    ) -> dict[str, Any]:
        """Actively call an action provided by the peer, and wait for the response."""
        self.seq_id_index += 1
        this_seq_id = self.seq_id_index
        request = ActionRequest.make_request(this_seq_id, action.value, data)
        # wait for response
        future = asyncio.Future[ActionResponse]()
        self.resp_waiters[this_seq_id] = future
        await self.conn.send(json.dumps(request.model_dump()))
        try:
            response = await asyncio.wait_for(future, timeout)
            if response.code != 0:
                raise ActionCallError(f"{response.message}")
            return response.data
        except asyncio.TimeoutError:
            raise ActionCallTimeoutError(f"Action {action.value} call timed out")
        except Exception as e:
            raise ActionCallError(f"{e.__class__.__name__}: {str(e)}")
        finally:
            if this_seq_id in self.resp_waiters:
                del self.resp_waiters[this_seq_id]
            if this_seq_id in self.resp_queues:
                del self.resp_queues[this_seq_id]

    async def call_action_generator(
        self, action: ActionType, data: dict[str, Any], timeout: float = 15.0
    ) -> AsyncIterator[dict[str, Any]]:
        self.seq_id_index += 1
        this_seq_id = self.seq_id_index
        request = ActionRequest.make_request(this_seq_id, action.value, data)

        # Create a queue for streaming responses
        queue = asyncio.Queue[ActionResponse]()
        self.resp_queues[this_seq_id] = queue

        await self.conn.send(json.dumps(request.model_dump()))

        try:
            while True:
                try:
                    response = await asyncio.wait_for(queue.get(), timeout)
                    if response.code != 0:
                        raise ActionCallError(f"{response.message}")

                    if response.chunk_status == ChunkStatus.CONTINUE:
                        yield response.data
                    elif response.chunk_status == ChunkStatus.END:
                        break
                except asyncio.CancelledError:
                    break
                except asyncio.TimeoutError:
                    raise ActionCallTimeoutError(
                        f"Action {action.value} call timed out"
                    )
                except Exception as e:
                    raise ActionCallError(f"{e.__class__.__name__}: {str(e)}")
        finally:
            if this_seq_id in self.resp_queues:
                del self.resp_queues[this_seq_id]

    # decorator to register an action
    def action(
        self, name: ActionType
    ) -> Callable[
        [
            Callable[
                [dict[str, Any]],
                Coroutine[
                    Any,
                    Any,
                    Union[ActionResponse, AsyncGenerator[ActionResponse, None]],
                ],
            ]
        ],
        Callable[
            [dict[str, Any]],
            Coroutine[
                Any, Any, Union[ActionResponse, AsyncGenerator[ActionResponse, None]]
            ],
        ],
    ]:
        def decorator(
            func: Callable[
                [dict[str, Any]],
                Coroutine[
                    Any,
                    Any,
                    Union[ActionResponse, AsyncGenerator[ActionResponse, None]],
                ],
            ],
        ) -> Callable[
            [dict[str, Any]],
            Coroutine[
                Any, Any, Union[ActionResponse, AsyncGenerator[ActionResponse, None]]
            ],
        ]:
            self.actions[name.value] = func
            return func

        return decorator
