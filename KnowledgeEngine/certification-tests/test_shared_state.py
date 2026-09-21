"""Real SDK objects; storage/HTTP are explicit local fixtures, not live services."""
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = ['DifyDatasetsConnector', 'FastGPTConnector', 'RAGFlowConnector']


def load_plugin(name):
    # Runtime uses one process per installation. Clear package names for this test loader.
    for key in list(sys.modules):
        if key == 'components' or key.startswith('components.'):
            del sys.modules[key]
    sys.path.insert(0, str(ROOT / name))
    try:
        spec = importlib.util.spec_from_file_location('candidate_main', ROOT / name / 'main.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        from importlib import import_module
        engine = import_module('components.knowledge_engine.' + ('langrag' if name == 'LangRAG' else 'engine'))
        return getattr(mod, name), getattr(engine, name)
    finally:
        sys.path.pop(0)


class StorageFixture:
    """Explicit fixture for Host's installation-bound storage, not production storage."""
    def __init__(self):
        self.data = {}
        self.fail = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def get_plugin_storage_keys(self):
        if self.fail:
            raise RuntimeError('fixture storage offline')
        return list(self.data)

    async def get_plugin_storage(self, key):
        if self.fail:
            raise RuntimeError('fixture storage offline')
        return self.data[key]

    async def set_plugin_storage(self, key, value):
        # A detached Host commit survives cancellation of the caller, like real RPC.
        async def commit():
            self.started.set()
            await self.release.wait()
            if self.fail:
                raise RuntimeError('fixture ambiguous commit')
            self.data[key] = value
        await asyncio.shield(asyncio.create_task(commit()))


def bind(plugin_cls, storage):
    plugin = plugin_cls()
    for name in ['get_plugin_storage_keys', 'get_plugin_storage', 'set_plugin_storage']:
        setattr(plugin, name, getattr(storage, name))
    return plugin


def configuration(marker):
    return {'api_base_url': 'https://fixture.invalid', 'api_key': marker,
            'dify_apikey': marker, 'dataset_id': marker, 'dataset_ids': marker}


@pytest.mark.asyncio
@pytest.mark.parametrize('name', CONNECTORS)
async def test_connector_restart_isolation_and_delete(name, monkeypatch):
    pc, ec = load_plugin(name)
    calls = []
    async def service(request):
        calls.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json={'code': 0, 'data': []})
        return httpx.Response(200, json={'code': 200 if name == 'FastGPTConnector' else 0})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client(transport=httpx.MockTransport(service), **kw))
    a, b = StorageFixture(), StorageFixture()
    ea, eb = ec(), ec()
    ea.plugin, eb.plugin = bind(pc, a), bind(pc, b)
    config = configuration('A')
    await ea.on_knowledge_base_create('same-kb', config)
    config['api_key'] = 'MUTATED'
    await eb.on_knowledge_base_create('same-kb', configuration('B'))
    restarted = ec()
    restarted.plugin = bind(pc, a)
    assert await restarted.delete_document('same-kb', 'doc') is True
    assert calls[-1].headers['authorization'] == 'Bearer A'
    assert await eb.delete_document('same-kb', 'doc') is True
    assert calls[-1].headers['authorization'] == 'Bearer B'
    await restarted.on_knowledge_base_delete('same-kb')
    assert await restarted.delete_document('same-kb', 'doc') is False
    assert await eb.delete_document('same-kb', 'doc') is True


@pytest.mark.asyncio
@pytest.mark.parametrize('name', CONNECTORS)
async def test_cancelled_config_commit_cannot_resurrect_deleted_kb(name):
    pc, ec = load_plugin(name)
    store = StorageFixture()
    engine = ec()
    engine.plugin = bind(pc, store)
    store.release.clear()
    # Empty credentials avoid the optional RAGFlow validation request.
    write = asyncio.create_task(engine.on_knowledge_base_create('kb', {'marker': 'A'}))
    try:
        await asyncio.wait_for(store.started.wait(), .3)
        write.cancel()
        await asyncio.sleep(0)
        write.cancel()
        delete = asyncio.create_task(engine.on_knowledge_base_delete('kb'))
        await asyncio.sleep(.01)
        assert not delete.done()
        store.release.set()
        with pytest.raises(asyncio.CancelledError):
            await write
        await delete
        restarted = ec()
        restarted.plugin = bind(pc, store)
        assert await restarted.delete_document('kb', 'doc') is False
    finally:
        store.release.set()
        await asyncio.gather(write, return_exceptions=True)


@pytest.mark.asyncio
async def test_langrag_telemetry_is_per_plugin_and_survives_restart():
    pc, _ = load_plugin('LangRAG')
    sa, sb = StorageFixture(), StorageFixture()
    a, b = bind(pc, sa), bind(pc, sb)
    await a.initialize()
    await b.initialize()
    assert hasattr(a, 'telemetry'), 'Telemetry must belong to the installation plugin'
    await a.telemetry.record_delete(collection_id='same', document_id='private-A', status='completed', duration_ms=1)
    assert (await b.telemetry.snapshot())['recent']['delete'] == []
    metrics = await b.telemetry.prometheus()
    warning_line = next(line for line in metrics.splitlines() if line.startswith('langrag_alerts_active{') and 'severity="warning"' in line)
    assert warning_line.endswith(' 0'), 'SDK persistence must not report JSONL-disabled warning'
    a2 = bind(pc, sa)
    await a2.initialize()
    assert (await a2.telemetry.snapshot())['recent']['delete'][0]['document_id'] == 'private-A'
    await a2.telemetry.clear()
    a3 = bind(pc, sa)
    await a3.initialize()
    assert (await a3.telemetry.snapshot())['recent']['delete'] == []


@pytest.mark.asyncio
async def test_text_parser_is_offloop(monkeypatch):
    load_plugin('LangRAG')
    from components.knowledge_engine.parser import FileParser
    import threading
    parser = FileParser()
    main_thread = threading.get_ident()
    monkeypatch.setattr(parser, '_decode_text', lambda data: str(threading.get_ident()))
    for filename in ['doc.txt', 'doc.unknown']:
        assert await parser.parse(b'x', filename) != str(main_thread)
