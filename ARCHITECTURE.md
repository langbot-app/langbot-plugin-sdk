# Architecture

This document maps the `langbot-plugin-sdk` repository. It explains the durable structure and cross-process contracts. For working rules, commands, and pitfalls, see `AGENTS.md`.

## What This Repository Is

`langbot-plugin-sdk` is the infrastructure package behind LangBot's plugin and sandbox systems. It is published to PyPI as `langbot-plugin` and pinned by the LangBot main repo.

The package has four roles:

- **Plugin SDK**: public APIs and entities imported by plugin authors.
- **CLI**: `lbp`, used to scaffold, run, debug, build, publish, and launch runtimes.
- **Plugin Runtime**: `lbp rt`, the host process that manages plugin packages and plugin processes.
- **Box Runtime**: `lbp box`, the sandbox runtime used by LangBot's Box subsystem.

The runtime code under `src/langbot_plugin/runtime/` is AGPL; the rest of the repo is Apache 2.0.

## Repository Boundary

This repo is coupled to LangBot but owns different things.

- The LangBot main repo owns product behavior, HTTP API, web UI, platform adapters, pipeline execution, model/tool orchestration, persistence, skills integration, and the LangBot-side runtime connectors.
- This SDK repo owns plugin author APIs, shared message/event/context entities, the action RPC protocol, `lbp`, Plugin Runtime implementation, and Box Runtime implementation.
- Plugins import this package directly; LangBot also imports it for shared entities and runtime protocols.

If a change alters shared entities, component contracts, action names/payloads, runtime behavior, or Box models, update/test both repos in lockstep.

## Top-Level Layout

```text
langbot-plugin-sdk/
├── src/langbot_plugin/
│   ├── api/                  # Public plugin-author SDK
│   │   ├── definition/       # BasePlugin, components, manifests
│   │   ├── entities/         # Contexts, events, builtin platform/provider models
│   │   └── proxies/          # APIs exposed to plugin code
│   ├── cli/                  # `lbp` entrypoint and subcommands
│   ├── runtime/              # Plugin Runtime (`lbp rt`)
│   ├── box/                  # Box Runtime (`lbp box`)
│   ├── entities/io/          # Action RPC request/response/error/action models
│   ├── assets/               # Scaffolding templates and page SDK asset
│   └── utils/
├── docs/                     # Supplemental protocol/component docs
├── tests/                    # Unit and black-box tests
├── pyproject.toml
└── README.md
```

## Public Plugin SDK

Plugin-facing APIs live under `src/langbot_plugin/api/`.

- `definition/plugin.py` defines `BasePlugin`.
- `definition/components/` defines component base classes.
- `definition/components/manifest.py` defines component manifest models.
- `entities/` defines event/context/message/provider data models passed across LangBot, runtime, and plugin code.
- `proxies/` defines methods plugins can call back into LangBot, such as messaging, storage, model invocation, tools, RAG, parser, and query-scoped APIs.

Plugins extend LangBot through six component types:

- `Command`
- `Tool`
- `EventListener`
- `KnowledgeEngine`
- `Parser`
- `Page`

The CLI scaffolds components via `lbp comp <Type>`. Component templates live under `src/langbot_plugin/assets/templates/`; generation logic lives under `src/langbot_plugin/cli/gen/`.

## CLI Architecture

`lbp` is declared in `pyproject.toml` and enters at `src/langbot_plugin/cli:main`, implemented by `src/langbot_plugin/cli/__init__.py`.

Subcommands:

- `init`: scaffold a plugin project.
- `comp`: generate a plugin component.
- `run`: run/remote-debug a plugin against a Runtime debug server.
- `build`: package a plugin zip.
- `publish`: publish a plugin to the marketplace.
- `login` / `logout`: marketplace authentication.
- `rt`: launch the Plugin Runtime.
- `box`: launch the Box Runtime.
- `ver`: print package version.

Subcommand implementations live under `cli/commands/`, `cli/run/`, and `cli/gen/`. CLI i18n lives under `cli/locales/`.

## Action RPC Protocol

The runtime protocol is a bidirectional action RPC protocol over stdio or WebSocket. It is implemented by `runtime/io/handler.py` and data models under `entities/io/`.

Request shape:

```json
{ "seq_id": 1, "action": "action_name", "data": {} }
```

Tenant-scoped control actions must carry a complete, trusted installation
binding without placing authority in the action payload:

```json
{
  "seq_id": 1,
  "action": "action_name",
  "data": {},
  "context": {
    "instance_uuid": "instance-id",
    "workspace_uuid": "workspace-id",
    "placement_generation": 1,
    "installation_uuid": "installation-id",
    "runtime_revision": 1,
    "artifact_digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  }
}
```

`SET_RUNTIME_CONFIG` is the instance-scoped handshake. It carries no Workspace
context and accepts this frozen payload:

```json
{
  "runtime_identity": {
    "instance_uuid": "instance-id",
    "runtime_id": "short-lived-runtime-id"
  },
  "worker_policy": {
    "max_cpus": 1.0,
    "max_memory_mb": 512,
    "max_pids": 128,
    "max_open_files": 256,
    "max_file_size_mb": 512,
    "require_hard_limits": true
  },
  "runtime_profile": "shared",
  "cloud_service_url": "https://space.langbot.app"
}
```

The Runtime identity and worker policy can be repeated exactly after a control
reconnect but cannot be changed for the life of the Runtime process. A new
authenticated control handler atomically supersedes the old handler; old
requests fail even if the old transport has not finished closing.

After the handshake, every tenant-scoped LangBot-to-Runtime action (including
file chunks) requires the complete immutable tuple
`(instance_uuid, workspace_uuid, placement_generation, installation_uuid,
runtime_revision, artifact_digest)`. Missing context, a different instance, or
an attempted generation/revision/artifact rebind fails closed. Instance-scoped
actions reject tenant context. Plugin payload fields are never authoritative
for these bindings.

In the `shared` profile, `PluginManager` indexes desired state by the complete
installation binding. The instance-scoped `RECONCILE_PLUGIN_INSTALLATIONS`
action replays the authoritative set, while tenant-scoped
`APPLY_PLUGIN_INSTALLATION` and `REMOVE_PLUGIN_INSTALLATION` actions change one
installation. Newer placement generations or Runtime revisions fence the old
worker immediately; stale or cross-Workspace transitions fail closed.

Plugin packages are verified against `artifact_digest` and extracted once into
a read-only `artifacts/sha256/<digest>/code` tree. Installations may share that
code tree, but each gets a separate process and private `home`, `tmp`, and `data`
directories. A worker receives a short-lived, one-use registration capability
bound to the complete installation tuple; it cannot select its own tenant scope.

Shared workers launch through nsjail with policy-owned cgroup CPU, memory, and
PID limits plus file/process rlimits. If `require_hard_limits` is true, missing
nsjail or cgroup v2 delegation makes configuration fail closed. Artifact `.env`
files are not loaded in the shared profile. The default `oss_dev` profile keeps
the direct-process and `.env` behavior needed for local open-source development.

Response shape:

```json
{ "seq_id": 1, "code": 0, "message": "success", "data": {}, "chunk_status": "continue" }
```

Core mechanics:

- `seq_id` correlates responses to requests.
- `context` carries trusted tenant/installation authority independently of
  plugin-controlled `data`; it is mandatory on tenant control actions.
- Messages with `action` are requests; messages with `code` are responses.
- Each peer may initiate requests on the same connection.
- `Handler.call_action()` waits for one response.
- `Handler.call_action_generator()` consumes streamed responses.
- Streaming emits `chunk_status: "continue"` chunks and ends with `"end"`.
- File transfer uses `CommonAction.FILE_CHUNK` with 16KB base64 chunks stored
  under `data/temp/lbp/`. Transfer keys are high-entropy opaque basenames; the
  receiver rejects absolute paths, separators, `..`, and unsafe extensions.

Action enums are the protocol contract:

- `CommonAction`
- `PluginToRuntimeAction`
- `RuntimeToPluginAction`
- `LangBotToRuntimeAction`
- `RuntimeToLangBotAction`
- `LangBotToBoxAction`

Do not duplicate action strings outside these enums.

## Plugin Runtime

`lbp rt` enters `runtime/app.py::main()` and builds `RuntimeApplication`.

Runtime graph:

```text
LangBot PluginRuntimeConnector
  ↔ control connection
  ↔ RuntimeApplication
  → PluginManager
  → PluginContainer(s)
  ↔ PluginConnectionHandler(s)
  ↔ plugin process(es)
```

Important modules:

- `runtime/app.py`: selects stdio vs WebSocket control transport, starts control/debug servers, launches plugin manager tasks.
- `runtime/context.py`: shared runtime context object.
- `runtime/settings.py`: runtime settings, including marketplace/cloud URL.
- `runtime/plugin/mgr.py`: plugin discovery, installation, dependency checks, launch, shutdown, event/tool/command/RAG/page dispatch.
- `runtime/plugin/container.py`: loaded plugin package, manifest, component containers, status.
- `runtime/io/handlers/control.py`: actions LangBot calls on the Runtime.
- `runtime/io/handlers/plugin.py`: actions the Runtime calls on plugin processes.
- `runtime/io/controllers/`: stdio/WebSocket server and client controllers.
- `runtime/io/connections/`: transport-specific connection implementations.

The Runtime has two external channels:

- **control channel**: LangBot ↔ Runtime, stdio or `:5400/control/ws` by default.
- **debug channel**: plugin dev process ↔ Runtime, WebSocket `:5401/plugin/debug/ws` by default.

Installed plugin processes do not authenticate with the shared debug key. For
each child launch, the Runtime reads the installed `manifest.yaml`, issues a
short-lived one-use registration capability bound to that author/name, and
passes only that capability to the child. The capability is consumed before
Host settings are requested, cannot be replayed, and the plugin must preserve
the same manifest identity after initialization. On Windows the child receives
an explicit environment allowlist, so Runtime and Box control secrets are not
inherited.

WebSocket control requires the high-entropy
`LANGBOT_PLUGIN_RUNTIME_CONTROL_TOKEN` in the
`X-LangBot-Plugin-Runtime-Token` handshake header. The debug server never
accepts an empty key: it validates an explicitly configured `PLUGIN_DEBUG_KEY`
or generates one at process start, and `lbp run` sends that value in the
`X-LangBot-Plugin-Debug-Key` handshake header for explicit development
sessions. Windows production children use their one-use registration
capability in `X-LangBot-Plugin-Registration-Capability` instead. The
instance-scoped `SET_RUNTIME_CONFIG` handshake and per-action installation
bindings are authorization fences after transport authentication; neither is a
substitute for authenticating the peer.

Installed plugins are stored under `data/plugins/{author}__{name}`. Runtime plugin processes normally run as separate Python processes and connect back via stdio or debug WebSocket.

## Box Runtime

`lbp box` enters `box/server.py::main()` and serves `BoxRuntime` through action RPC.

Box graph:

```text
LangBot BoxService
  ↔ BoxRuntimeConnector
  ↔ BoxServerHandler
  → BoxRuntime
  → Backend session(s)
  → Docker/Podman, nsjail, or E2B sandbox
```

Important modules:

- `box/server.py`: CLI entrypoint, aiohttp WebSocket routes, `BoxServerHandler` action registration.
- `box/runtime.py`: session lifecycle, per-session locks, TTL cleanup, command execution, managed processes.
- `box/models.py`: `BoxSpec`, execution results, managed-process specs.
- `box/client.py`: action-RPC client used by LangBot-side connector/service.
- `box/actions.py`: `LangBotToBoxAction` enum.
- `box/backend.py`: backend abstraction and local backend selection.
- `box/nsjail_backend.py`: nsjail backend.
- `box/e2b_backend.py`: E2B backend.
- `box/skill_store.py`: Box-owned skill package CRUD and install/preview helpers.
- `box/security.py`: path/security helper logic.

Default Box WebSocket endpoints on port `5410`:

- `/rpc/ws`: action RPC control channel.
- `/v1/sessions/{session_id}/managed-process/ws`: legacy default process stdio relay.
- `/v1/sessions/{session_id}/managed-process/{process_id}/ws`: named process stdio relay.

Box keeps durable skill/storage paths in an `(instance, workspace)` namespace,
while sandbox sessions and managed processes use an
`(instance, workspace, placement_generation)` namespace. Authenticated tenant
RPCs advance a monotonic generation fence, cancel in-flight older RPCs, and
retire older sessions. Managed-process relay handshakes carry Workspace and
generation in authenticated headers; an attached relay closes as soon as that
generation becomes stale.

There is no supported `python -m langbot_plugin.box` entrypoint; use `lbp box`.

## Backend Selection

Box can execute through multiple sandbox backends:

- Docker/Podman through the local CLI backend path.
- nsjail for local Linux sandboxing.
- E2B for remote cloud sandboxes.

LangBot sends Box config during initialization. Backend selection is controlled by LangBot's `box.backend` config (`local`, `docker`, `nsjail`, `e2b`) and the Box runtime's backend availability probes.

A false “no backend” often means Docker exists but the user cannot access the Docker socket. nsjail inside containers requires host cgroup namespace for cgroup v2 limits if hard memory/pid/cpu enforcement is expected.

## Cross-Repo Development Flow

When changing shared contracts:

1. Change this SDK repo first or in the same branch set.
2. Install the local SDK into LangBot's virtualenv: `uv pip install .` from this repo while LangBot's `.venv` is active.
3. Run LangBot with `uv run --no-sync ...` so `uv` does not replace the local SDK with the pinned PyPI package.
4. Exercise the exact path changed: plugin stdio, plugin WebSocket, `lbp run`, `lbp rt`, `lbp box`, Box WebSocket, or Box stdio.

Workspace action-context support starts in SDK `0.4.15`. The instance-scoped
Runtime handshake and complete `InstallationBinding` extend that protocol on
the multi-tenant branch and require a coordinated LangBot Core change before
release. Until a matching SDK version is published, Core must pin the exact
pushed SDK commit; the already-published `0.4.14` artifact does not contain any
of these contracts and must not be used as a compatibility alias.

The SDK `AGENTS.md` keeps the short command checklist; this file keeps the structural map.

## Design Biases

- Keep plugin-author SDK APIs stable and explicit.
- Treat action enums and Pydantic models as cross-process API contracts.
- Keep runtime process management separate from LangBot product logic.
- Keep Box sandbox semantics in `box/`; LangBot should call Box through the service/client protocol.
- Prefer tests around protocol shape and black-box CLI behavior when changing runtime boundaries.
