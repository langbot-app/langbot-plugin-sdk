"""Installation-local state using the SDK-bound Host proxy, never caller scope.

Bundled in each independent archive. No filesystem/global tenant registry.
"""
import asyncio
import hashlib
import json
from functools import wraps
from contextlib import asynccontextmanager
import httpx

HTTP_TOTAL_TIMEOUT = 150.0


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


class ConfigStore:
    """No credential cache: every delete resolves durable installation storage.

    A JSON null tombstone makes missing KBs explicit without ambiguous delete RPCs.
    The one mutation lock also orders ingest/delete/create inside this worker.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._state = SerialState()
        self._http_slots = asyncio.Semaphore(4)

    @asynccontextmanager
    async def http_client(self):
        # Include queueing and the whole response body in the deadline, not just
        # individual socket reads. Clients/credentials never survive a call.
        async with asyncio.timeout(HTTP_TOTAL_TIMEOUT):
            async with self._http_slots:
                async with httpx.AsyncClient() as client:
                    yield client

    @staticmethod
    def _key(kb_id):
        return "ke.config.v1." + hashlib.sha256(kb_id.encode()).hexdigest()

    async def _save_config(self, kb_id, config):
        value = json.dumps(config, ensure_ascii=False).encode()
        if len(value) > 65536:
            raise ValueError("Knowledge-base configuration exceeds 64 KiB")
        await self._state.write(self.plugin, self._key(kb_id), value)

    async def _load_config(self, kb_id):
        key = self._key(kb_id)
        # Only an authoritative keys response establishes absence; RPC errors propagate.
        if key not in await self.plugin.get_plugin_storage_keys():
            return None
        value = json.loads(await self.plugin.get_plugin_storage(key))
        if value is not None and not isinstance(value, dict):
            raise ValueError("Invalid persisted knowledge-base configuration")
        return value
