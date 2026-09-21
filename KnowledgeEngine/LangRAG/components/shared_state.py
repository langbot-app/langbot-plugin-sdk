"""Installation-local state using the SDK-bound Host proxy, never caller scope.

Bundled in each independent archive. No filesystem/global tenant registry.
"""
import asyncio
from functools import wraps


async def settle(task):
    """Do not release a lock while a dispatched Host commit can still finish."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        # Retrieve errors too; the operation itself has already fenced unsafe state.
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


class SerialState:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.fenced = False

    async def run(self, operation):
        async with self.lock:
            if self.fenced:
                raise RuntimeError("Installation state fenced after ambiguous storage failure; reconcile before restart")
            return await settle(asyncio.create_task(operation()))

    async def write(self, plugin, key, value):
        try:
            await plugin.set_plugin_storage(key, value)
        except BaseException:
            self.fenced = True
            raise


def serialized(method):
    @wraps(method)
    async def call(self, *args, **kwargs):
        return await self._state.run(lambda: method(self, *args, **kwargs))
    return call
