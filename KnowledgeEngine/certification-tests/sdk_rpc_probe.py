"""Exact artifact, real b5 discovery/controller/proxies and WebSocket RPC.

Two native InstallationBinding connections; fake Host storage/vector/model and
fake local HTTP provider. No Cloud, real provider, nsjail or certificate claims.
"""
import asyncio
import base64
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import sys
from contextlib import asynccontextmanager

import websockets
from aiohttp import web
from langbot_plugin.utils.discover.engine import ComponentDiscoveryEngine
from langbot_plugin.cli.utils.page_components import discover_plugin_components
from langbot_plugin.cli.run.controller import PluginRuntimeController
from langbot_plugin.cli.run.handler import PluginRuntimeHandler
from langbot_plugin.runtime.io.handler import Handler, ActionResponse
from langbot_plugin.runtime.io.connections.ws import WebSocketConnection
from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction as R, PluginToRuntimeAction as P
from langbot_plugin.entities.io.context import InstallationBinding
from langbot_plugin.entities.io.errors import ActionCallError

CODE, OUT, NAME, DIGEST = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
os.chdir(CODE)
sys.path.insert(0, str(CODE))


async def main():
    assert importlib.metadata.version('langbot-plugin') == '0.6.0b5'
    before = {str(p.relative_to(CODE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in CODE.rglob('*') if p.is_file()}
    discovery = ComponentDiscoveryEngine()
    manifest = discovery.load_component_manifest('manifest.yaml', no_save=True)
    components = discover_plugin_components(manifest, discovery)
    kinds = sorted(c.kind for c in components)
    assert kinds == (['KnowledgeEngine', 'Page'] if NAME == 'LangRAG' else ['KnowledgeEngine'])
    assert manifest.execution.shared_runtime == 'shared-runtime-v1'
    stores, vectors, calls = {}, {}, []
    http_calls = []
    async def provider(request):
        body = await request.read()
        marker = request.headers['Authorization'].split()[-1]
        http_calls.append((request.method, request.path, marker))
        await asyncio.sleep(.002)
        if request.path.endswith('/retrieve'):
            return web.json_response({'records': [{'segment': {'id': 'seg', 'content': marker}, 'score': .9}]})
        if request.path.endswith('/searchTest'):
            return web.json_response({'data': [{'id': 'seg', 'q': marker, 'score': .9}]})
        if request.path.endswith('/retrieval'):
            return web.json_response({'code': 0, 'data': {'chunks': [{'id': 'seg', 'content': marker, 'similarity': .9}]}})
        if request.path.endswith('/create-by-file'):
            assert b'fixture file' in body
            return web.json_response({'document': {'id': 'remote-doc'}})
        if request.path.endswith('/localFile'):
            assert b'fixture file' in body
            return web.json_response({'code': 200, 'data': {'collectionId': 'remote-doc'}})
        if request.method == 'POST' and request.path.endswith('/documents'):
            assert b'fixture file' in body
            return web.json_response({'code': 0, 'data': [{'id': 'remote-doc'}]})
        if request.method == 'GET':
            return web.json_response({'code': 0, 'data': []})
        return web.json_response({'code': 200 if NAME == 'FastGPTConnector' else 0})
    app = web.Application()
    app.router.add_route('*', '/{path:.*}', provider)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
    def binding(label):
        return InstallationBinding(instance_uuid='fixture-instance', workspace_uuid='workspace-'+label,
            placement_generation=1, installation_uuid='installation-'+label, runtime_revision=1, artifact_digest=DIGEST)
    a, b = binding('A'), binding('B')

    @asynccontextmanager
    async def installation(scope):
        label = scope.workspace_uuid
        store = stores.setdefault(label, {})
        rows = vectors.setdefault(label, {})
        controller = PluginRuntimeController(manifest, components, False, '')
        ready = asyncio.get_running_loop().create_future()
        async def connected(ws):
            os.environ['LANGBOT_PLUGIN_FILE_STORAGE_DIR'] = str(OUT / 'rpc-tmp' / NAME / label / 'worker')
            handler = PluginRuntimeHandler(WebSocketConnection(ws), controller.initialize)
            controller.handler = handler
            handler.plugin_container = controller.plugin_container
            ready.set_result(handler)
            await handler.run()
        async with websockets.serve(connected, '127.0.0.1', 0) as server:
            async with websockets.connect(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}') as ws:
                host = Handler(WebSocketConnection(ws), file_storage_dir=OUT / 'rpc-tmp' / NAME / label / 'host')
                def check(action, data):
                    assert host.current_action_context == scope, 'SDK proxy lost its immutable binding'
                    calls.append((label, action))
                @host.action(P.GET_PLUGIN_STORAGE_KEYS)
                async def keys(data):
                    check('keys', data)
                    return ActionResponse.success({'keys': list(store)})
                @host.action(P.GET_PLUGIN_STORAGE)
                async def get(data):
                    check('get', data)
                    return ActionResponse.success({'value_base64': store[data['key']]})
                @host.action(P.SET_PLUGIN_STORAGE)
                async def set_value(data):
                    check('set', data)
                    await asyncio.sleep(.002)
                    store[data['key']] = data['value_base64']
                    return ActionResponse.success({})
                @host.action(P.INVOKE_EMBEDDING)
                async def embed(data):
                    check('embedding', data)
                    return ActionResponse.success({'vectors': [[1.0] for _ in data['texts']]})
                @host.action(P.VECTOR_UPSERT)
                async def upsert(data):
                    check('upsert', data)
                    for id_, meta in zip(data['ids'], data['metadata']):
                        rows[id_] = {'id': id_, 'distance': .1, 'metadata': meta}
                    return ActionResponse.success({})
                @host.action(P.VECTOR_SEARCH)
                async def search(data):
                    check('search', data)
                    return ActionResponse.success({'results': list(rows.values())[:data['top_k']]})
                @host.action(P.VECTOR_DELETE)
                async def delete(data):
                    check('delete', data)
                    n = len(rows)
                    rows.clear()
                    return ActionResponse.success({'count': n})
                @host.action(P.GET_KNOWLEDEGE_FILE_STREAM)
                async def file_stream(data):
                    check('file', data)
                    key = await host.send_file(b'fixture file', 'txt', action_context=scope)
                    return ActionResponse.success({'file_key': key})
                task = asyncio.create_task(host.run())
                handler = await ready
                async def call(action, data, context=scope):
                    return await host.call_action(action, data, action_context=context, timeout=8)
                try:
                    await call(R.INITIALIZE_PLUGIN, {'plugin_settings': {'enabled': True, 'priority': 0, 'plugin_config': {'marker': label}}})
                    assert controller.plugin_container.plugin_instance.get_config() == {'marker': label}
                    assert handler.require_bound_action_context() == scope
                    yield call, controller
                finally:
                    await host.close()
                    await handler.close()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await controller.cleanup_instances()

    def config(marker):
        return {'api_base_url': url, 'api_key': marker, 'dify_apikey': marker,
                'dataset_id': marker, 'dataset_ids': marker, 'embedding_model_uuid': 'fixture-embedding'}
    async def ingest(call, marker):
        ctx = {'knowledge_base_id': 'same-kb', 'creation_settings': config(marker),
               'file_object': {'metadata': {'filename': 'doc.txt', 'document_id': 'same-doc',
                 'knowledge_base_id': 'same-kb', 'file_size': 12, 'mime_type': 'text/plain'}, 'storage_path': 'fixture-file'}}
        if NAME == 'LangRAG':
            ctx['parsed_content'] = {'text': 'private-' + marker}
        result = await call(R.INGEST_DOCUMENT, {'context': ctx})
        assert result['status'] == ('completed' if NAME == 'LangRAG' else 'processing'), result
    async def retrieve(call, marker):
        result = await call(R.RETRIEVE_KNOWLEDGE, {'retriever_name': '', 'retrieval_context': {
            'query': 'fixture query', 'knowledge_base_id': 'same-kb', 'creation_settings': config(marker), 'retrieval_settings': {'top_k': 2}}})
        assert result['total_found'] == 1, result
        assert marker in result['results'][0]['content'][0]['text'], result
        return result
    page_id = next((c.metadata.name for c in components if c.kind == 'Page'), None)
    async def page(call, endpoint, method='GET'):
        return await call(R.PAGE_API, {'page_id': page_id, 'endpoint': endpoint, 'method': method, 'body': {}})
    try:
        async with installation(a) as (ca, cta), installation(b) as (cb, ctb):
            await asyncio.gather(ingest(ca, 'A'), ingest(cb, 'B'))
            await asyncio.gather(*(retrieve(ca if i % 2 == 0 else cb, 'A' if i % 2 == 0 else 'B') for i in range(12)))
            try:
                await ca(R.ON_KB_DELETE, {'kb_id': 'same-kb'}, context=b)
            except ActionCallError:
                pass
            else:
                raise AssertionError('Cross-Workspace action was accepted')
            assert cta.plugin_container.plugin_instance is not ctb.plugin_container.plugin_instance
            if NAME == 'LangRAG':
                sa, sb = await page(ca, '/snapshot'), await page(cb, '/snapshot')
                assert sa['data']['counters']['ingest.total'] == sb['data']['counters']['ingest.total'] == 1
                await page(ca, '/clear', 'POST')
                assert (await page(ca, '/snapshot'))['data']['counters'] == {}
                assert (await page(cb, '/snapshot'))['data']['counters']['ingest.total'] == 1
        # Fresh real controller objects recover each installation's durable state.
        async with installation(a) as (ca, _), installation(b) as (cb, _):
            if NAME == 'LangRAG':
                assert (await page(ca, '/snapshot'))['data']['counters'] == {}
                assert (await page(cb, '/snapshot'))['data']['counters']['ingest.total'] == 1
            result = await ca(R.DELETE_DOCUMENT, {'kb_id': 'same-kb', 'document_id': 'remote-doc'})
            assert result['success']
            if NAME != 'LangRAG':
                assert http_calls[-1][2] == 'A'
                await ca(R.ON_KB_DELETE, {'kb_id': 'same-kb'})
                assert not (await ca(R.DELETE_DOCUMENT, {'kb_id': 'same-kb', 'document_id': 'remote-doc'}))['success']
            await retrieve(cb, 'B')
        after = {str(p.relative_to(CODE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in CODE.rglob('*') if p.is_file()}
        assert before == after, 'Runtime wrote into shared artifact tree'
        report = {'name': NAME, 'sdk': '0.6.0b5', 'artifact_sha256': DIGEST, 'components': kinds,
                  'native_installation_bindings': 2, 'concurrent_retrievals': 12,
                  'cross_workspace_denied': True, 'restart_state_recovered': True,
                  'artifact_unchanged': True, 'host_calls': len(calls), 'http_calls': len(http_calls),
                  'scope': 'Real SDK loopback RPC; fake Host/provider; no production or nsjail execution'}
        (OUT / (NAME + '-rpc-results.json')).write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    logging.basicConfig(level=logging.CRITICAL)
    asyncio.run(asyncio.wait_for(main(), 80))
