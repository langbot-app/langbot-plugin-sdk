"""Task-local API binding shared by plugin and component methods."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import inspect
from typing import Any


@dataclass
class Invocation:
    handler: Any
    api: Any
    active: bool = True


_current: ContextVar[Invocation | None] = ContextVar("plugin_invocation", default=None)


@contextmanager
def bind_invocation(handler, api):
    invocation = Invocation(handler, api)
    token = _current.set(invocation)
    try:
        yield
    finally:
        invocation.active = False
        _current.reset(token)


def current_api(handler):
    invocation = _current.get()
    if invocation is None or invocation.handler is not handler:
        return None
    if not invocation.active:
        raise RuntimeError("Runner invocation has ended")
    return invocation.api


def run_scoped(method):
    """Use the same public method with the current Runner authorization, if any."""
    signature = inspect.signature(method)

    def target(instance, args, kwargs):
        api = current_api(instance.plugin_runtime_handler)
        if api is None:
            return method, (instance, *args), kwargs
        bound = signature.bind(instance, *args, **kwargs)
        arguments = dict(bound.arguments)
        arguments.pop("self")
        if method.__name__ == "call_tool":
            arguments.pop("session", None)
            arguments.pop("query_id", None)
        return getattr(api, method.__name__), (), arguments

    if inspect.isasyncgenfunction(method):

        @wraps(method)
        async def stream(self, *args, **kwargs):
            fn, positional, named = target(self, args, kwargs)
            async for item in fn(*positional, **named):
                yield item

        return stream

    @wraps(method)
    async def call(self, *args, **kwargs):
        fn, positional, named = target(self, args, kwargs)
        return await fn(*positional, **named)

    return call
