"""Task-local API binding shared by plugin and component methods."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import inspect
from types import MappingProxyType
from typing import Any, Mapping

from langbot_plugin.entities.io.context import InstallationBinding


def freeze_config(value: Any) -> Any:
    """Return an immutable invocation snapshot without sharing tenant objects."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): freeze_config(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_config(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_config(item) for item in value)
    return value


def thaw_config(value: Any) -> Any:
    """Return a recursively JSON-safe copy of an immutable config snapshot."""

    if isinstance(value, Mapping):
        return {str(key): thaw_config(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_config(item) for item in value]
    if isinstance(value, frozenset):
        return [thaw_config(item) for item in value]
    return value


@dataclass
class Invocation:
    handler: Any
    api: Any
    config: Mapping[str, Any] | None = None
    binding: InstallationBinding | None = None
    active: bool = True

    def require_active(self) -> None:
        if not self.active:
            raise RuntimeError("Plugin invocation has ended")


_current: ContextVar[Invocation | None] = ContextVar("plugin_invocation", default=None)


@contextmanager
def bind_invocation(
    handler,
    api=None,
    *,
    config: Mapping[str, Any] | None = None,
    binding: InstallationBinding | None = None,
):
    invocation = Invocation(
        handler,
        api,
        config=freeze_config(config or {}) if config is not None else None,
        binding=binding,
    )
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


def current_invocation(handler=None) -> Invocation | None:
    """Return the active task-local invocation, rejecting escaped background work."""

    invocation = _current.get()
    if invocation is None:
        return None
    if handler is not None and invocation.handler is not handler:
        return None
    if not invocation.active:
        raise RuntimeError("Plugin invocation has ended")
    return invocation


def invocation_capability(handler=None) -> Invocation | None:
    """Return the current revocable authority object for outbound boundaries."""

    invocation = _current.get()
    if invocation is None or (
        handler is not None and invocation.handler is not handler
    ):
        return None
    invocation.require_active()
    return invocation


def current_config(handler=None) -> Mapping[str, Any] | None:
    invocation = current_invocation(handler)
    return None if invocation is None else invocation.config


def current_binding(handler=None) -> InstallationBinding | None:
    invocation = current_invocation(handler)
    return None if invocation is None else invocation.binding


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
