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

Response shape:

```json
{ "seq_id": 1, "code": 0, "message": "success", "data": {}, "chunk_status": "continue" }
```

Core mechanics:

- `seq_id` correlates responses to requests.
- Messages with `action` are requests; messages with `code` are responses.
- Each peer may initiate requests on the same connection.
- `Handler.call_action()` waits for one response.
- `Handler.call_action_generator()` consumes streamed responses.
- Streaming emits `chunk_status: "continue"` chunks and ends with `"end"`.
- File transfer uses `CommonAction.FILE_CHUNK` with 16KB base64 chunks stored under `data/temp/lbp/`.

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

The SDK `AGENTS.md` keeps the short command checklist; this file keeps the structural map.

## Design Biases

- Keep plugin-author SDK APIs stable and explicit.
- Treat action enums and Pydantic models as cross-process API contracts.
- Keep runtime process management separate from LangBot product logic.
- Keep Box sandbox semantics in `box/`; LangBot should call Box through the service/client protocol.
- Prefer tests around protocol shape and black-box CLI behavior when changing runtime boundaries.
