# KnowledgeEngine shared-runtime candidates

These are **unsigned candidates**, not an assertion that Space certification,
publication, or production Cloud acceptance has completed. IDs are unchanged:
`langbot-team/DifyDatasetsConnector` 0.1.6, `langbot-team/FastGPTConnector` 0.1.4,
`langbot-team/LangRAG` 0.1.11, `langbot-team/RAGFlowConnector` 0.1.5.
All require the shipped `langbot-plugin==0.6.0b5` and opt into
`execution.sharedRuntime: shared-runtime-v1`.

## Scope and state audit

The native SDK contract is **one process/BasePlugin/component set per immutable
InstallationBinding**, not many tenants sharing an arbitrary plugin singleton.
The Runtime can share the verified read-only artifact/dependency trees. Only
Host-bound SDK proxies carry tenant authority; a KB ID, collection ID, request
field, environment override, or plugin-generated workspace label is not a scope.

| Surface | State and isolation | Concurrency/failure behavior |
| --- | --- | --- |
| All plugin configuration | SDK injects `BasePlugin.config` per installation | Never stored in a module or a cross-install cache |
| Dify/FastGPT/RAGFlow retrieval | Request-local settings, auth headers, HTTP client and response | Four HTTP sessions per component; 150-second total client-block deadline including queue/body; existing per-request inactivity timeouts retained |
| Connector create/ingest/delete | `ke.config.v1.<sha256(kb_id)>` in **SDK plugin storage**, not filesystem or invented tenant keys | One component mutation lock; defensive JSON snapshot; 64 KiB max configuration; null tombstone on KB deletion |
| Connector restart | Delete loads persisted settings using SDK proxy | Only authoritative key-list absence counts as missing; RPC/JSON failures propagate, not empty credentials |
| Connector cancellation | Dispatched mutation continues under its lock | Repeated caller cancellation cannot release the lock ahead of a remote commit; ambiguous storage failure fences later mutations |
| Connector external provider state | Dify document, FastGPT collection, RAGFlow upload/parse/GraphRAG/RAPTOR remain provider-owned | No automatic retry of ambiguous provider mutations; SDK installation isolation cannot isolate users who intentionally configure the same provider credential/dataset |
| LangRAG parsing/chunking | Per-operation bytes, text, strategy and metadata; per-plugin CPU executor admission | Two admitted thread jobs; cancellation retains the slot until the thread settles; 16 MiB internal parser input / 4 MiB parsed-text limits; text decoding and all strategy splitting off-loop |
| LangRAG vectors/embedding/rewrite/rerank | Only SDK Host proxies; collection/model settings stay request-local | Progressive embedding batches retained; ingest/delete serialized through completion; ambiguous vector mutations fence future mutations; retrieval remains concurrent |
| LangRAG telemetry and Page | One async telemetry store owned by `BasePlugin`, shared by its own Engine and Page | SDK storage, at most 100 persisted events and 192 KiB; serialized/shielded commits and clear; failed persistence visible in snapshot and mutation-fenced |
| LangRAG pure telemetry aggregator | Explicit-path JSONL support retained only for offline tooling/tests | No runtime singleton instance, import-time load, cwd writer or observability-directory environment override; production adapter configures **no file path** |
| Files and RPC transfers | Files read through SDK knowledge-file proxy | Real SDK owns installation-private transfer directories; no writes to artifact directory |
| Benchmark fixtures | Explicit offline Host/model/vector/storage substitutes | Not imported by the deployed runtime; never reported as external-provider E2E |

The mutation fence is intentionally fail-closed. After an ambiguous remote
commit, reconcile/quiesce Host activity before restarting the installation; an
ordinary read does not establish that no late commit remains. Parser threads
are bounded, not forcibly killable; production worker cgroup/rlimits remain
Runtime-owned.

### Upgrade notes

- The old connectors never persisted their in-memory KB credentials. There is
  no historical credential cache to migrate. Existing KBs acquire durable
  deletion settings on the next create/ingest call; deletion without those
  settings continues to return false rather than guessing credentials.
- LangRAG no longer reads the old cwd-relative JSONL history or arbitrary
  `LANGRAG_OBSERVABILITY_DIR`. Operational history starts anew in installation
  storage. Knowledge documents/vectors are Host-owned and are not migrated,
  erased or renamed. The bounded history/counters are diagnostic, not a durable
  accounting ledger; retained events are replayed after restart.
- No claims of cross-account provider dataset separation, real external model
  quality, Cloud installation, certificate verification or hard sandbox limits
  can be derived from these local fixtures.

## Reproduce local verification

Use a new virtual environment with Python 3.11+ and the actual released SDK:

```sh
uv venv /tmp/ke-check
uv pip install --python /tmp/ke-check/bin/python \
  langbot-plugin==0.6.0b5 pytest pytest-asyncio \
  -r KnowledgeEngine/LangRAG/requirements.txt \
  -r KnowledgeEngine/DifyDatasetsConnector/requirements.txt \
  -r KnowledgeEngine/FastGPTConnector/requirements.txt \
  -r KnowledgeEngine/RAGFlowConnector/requirements.txt
/tmp/ke-check/bin/python -m pytest KnowledgeEngine/certification-tests -q
(cd KnowledgeEngine/LangRAG && /tmp/ke-check/bin/python -m unittest discover -s tests -v)
/tmp/ke-check/bin/python KnowledgeEngine/certification-tests/verify_candidates.py \
  --evidence /tmp/ke-evidence
```

The last command builds with the real b5 `lbp`, verifies unsigned ZIPs through
`PluginArtifactStore`, runs genuine `PluginDependencyEnvironmentStore.prepare()`
using the SDK's **direct pip installer**, and verifies immutable dependency/cache
readback with no shadow SDK. It checks installed SDK Python files against wheel
RECORD hashes. Each exact extracted archive then runs genuine discovery,
initialization, proxy and bidirectional WebSocket RPC tests with two native
InstallationBindings. The Host and loopback HTTP provider are explicitly fake;
this checks protocol/config/storage isolation, not live Cloud or provider E2E.
The direct installer is not the production nsjail installer.

The JSON inventory must contain exactly all four plugin names, source-file and
archive hashes, dependency-environment digests, and successful per-artifact RPC
reports. Preserve these exact bytes for independent review; rebuilding ZIPs can
change raw hashes. Signing/publication and real two-Workspace Cloud acceptance
are separate release gates and are deliberately not performed here.
