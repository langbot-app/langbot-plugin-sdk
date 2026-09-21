"""Async, bounded telemetry persisted via the installation-bound SDK proxy.

No cwd writes, process environment path overrides, or global mutable store.
Telemetry is diagnostic: failures are surfaced in snapshots, not allowed to
turn an acknowledged vector operation into a failed/retried ingestion.
"""
import json

from components.shared_state import SerialState
from .telemetry import LangRAGTelemetry

KEY = 'langrag.telemetry.v1'
MAX_BYTES = 192 * 1024
MAX_EVENTS = 100


class InstallationTelemetry:
    start_timer = staticmethod(LangRAGTelemetry.start_timer)
    elapsed_ms = staticmethod(LangRAGTelemetry.elapsed_ms)
    new_trace_id = staticmethod(LangRAGTelemetry.new_trace_id)
    correlation_summary = staticmethod(LangRAGTelemetry.correlation_summary)

    def __init__(self, plugin):
        self.plugin = plugin
        self._state = SerialState()
        self._store = LangRAGTelemetry(max_history_events=MAX_EVENTS)
        self._error = None
        self._initialized = False

    async def initialize(self):
        async def load():
            if self._initialized:
                return
            if KEY in await self.plugin.get_plugin_storage_keys():
                raw = await self.plugin.get_plugin_storage(KEY)
                if len(raw) > MAX_BYTES:
                    raise ValueError('Telemetry snapshot too large')
                events = json.loads(raw)
                if not isinstance(events, list) or len(events) > MAX_EVENTS:
                    raise ValueError('Invalid telemetry snapshot')
                for event in events:
                    if not isinstance(event, dict) or not event.get('operation'):
                        raise ValueError('Invalid telemetry event')
                    self._store._record_event(event, persist=False)
                self._store._loaded_event_count = len(events)
            self._initialized = True
        try:
            await self._state.run(load)
        except Exception as exc:
            self._state.fenced = True
            self._error = type(exc).__name__
            raise

    async def _persist(self):
        events = list(self._store._events)[-MAX_EVENTS:]
        while True:
            raw = json.dumps(events, ensure_ascii=False).encode()
            if len(raw) <= MAX_BYTES:
                break
            events.pop(0)
        await self._state.write(self.plugin, KEY, raw)

    async def _record(self, method, kwargs):
        async def record():
            if not self._initialized:
                raise RuntimeError('Telemetry is not initialized')
            # Pure bounded in-memory aggregation; no file I/O is configured.
            getattr(self._store, method)(**kwargs)
            await self._persist()
        try:
            await self._state.run(record)
        except Exception as exc:
            self._error = type(exc).__name__

    async def record_ingest(self, **kwargs):
        await self._record('record_ingest', kwargs)

    async def record_retrieval(self, **kwargs):
        await self._record('record_retrieval', kwargs)

    async def record_embedding_batch(self, **kwargs):
        await self._record('record_embedding_batch', kwargs)

    async def record_delete(self, **kwargs):
        await self._record('record_delete', kwargs)

    async def snapshot(self):
        # Bounded CPU work off-loop; RLock protects the pure aggregation store.
        result = await self.plugin.offload.run(self._store.snapshot)
        result['persistence'] = {
            'enabled': True, 'path': 'sdk:plugin-storage',
            'loaded_events': self._store._loaded_event_count,
            'history_events': len(self._store._events), 'error': self._error,
        }
        result['alerts'] = [a for a in result['alerts'] if a['code'] != 'persistence_disabled']
        if self._error:
            result['alerts'].append({'severity': 'warning', 'code': 'persistence_error', 'message': self._error})
        result['health'] = self._store._health(result['alerts'])
        return result

    async def prometheus(self):
        snapshot = await self.snapshot()
        return await self.plugin.offload.run(self._store.prometheus, snapshot)

    async def clear(self):
        async def clear():
            await self._state.write(self.plugin, KEY, b'[]')
            self._store.clear()
        await self._state.run(clear)
