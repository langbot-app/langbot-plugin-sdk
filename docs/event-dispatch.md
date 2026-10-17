# Event dispatch admission and ordering

The Runtime dispatches EMIT_EVENT only to initialized, enabled, in-scope plugins
with a loaded EventListener component and an active handler. The component list
is refreshed from the worker after initialization, rather than inferred from a
Runner name or a pipeline binding. Plugins without a listener cannot consume
this RPC and must not introduce cross-worker head-of-line blocking.

Listeners still run serially. Their EventContext mutations flow to subsequent
plugins; prevent_postorder stops traversal. Query identity and trusted execution
scope validation remain in place. Exceptions, timeouts, and transport failures
retain their existing propagation behavior. This change does not isolate a slow
or faulty listener from later listeners. Nor does it filter an EventListener by
its per-event registered handlers: those registrations live inside the worker.
No concurrency, wire schema, plugin API, or package version changes are made.

Regression: tests/runtime/plugin/test_manager.py covers absent/non-listener
components, enabled/status/connection/binding admission, ordered mutation,
prevention, query identity, response provenance and subscriber failures.
The existing component-list test uses pytest's async lifecycle rather than
nested asyncio.run calls, avoiding an orphan event loop in mixed test suites.

The LANG-16 cross-repository harness in LangBot tests/manual/lang16_matrix.py
installs real local Runner/Listener packages. LANG16_SHORT=1 stops after faults;
LANG16_LISTENERS=1 adds real event subscribers and order/prevention assertions.
Run it through lang16_baseline.py with LANG16_MATRIX=1 and an isolated interpreter
selected by LANG16_CORE_PYTHON. Default enable_all_plugins remains enabled.
All service data, caches, ports and cleanup are task-owned. No real QQ traffic
or model calls are required. See LangBot docs/LANG16_LOCAL_QA.md for measured
results and the remaining network/long-history acceptance limits.
