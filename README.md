<div align="center">
<img src="docs/langbot-plugin-social.png" alt="LangBot Plugin SDK" />
</div>

<div align="center">

[![PyPI](https://img.shields.io/pypi/v/langbot-plugin)](https://pypi.org/project/langbot-plugin/)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

[Documentation](https://docs.langbot.app/zh/plugin/dev/tutor) ·
[Plugin Market](https://space.langbot.app) ·
[LangBot](https://github.com/langbot-app/LangBot)

</div>

## LangBot Plugin Infra

This repository is the shared infrastructure powering LangBot's plugin and
sandbox subsystems. It is published to PyPI as the single
[`langbot-plugin`](https://pypi.org/project/langbot-plugin/) package and ships
three things:

- **Plugin SDK & CLI** (`lbp`) — Python APIs, base classes and the `lbp`
  command for scaffolding, building, debugging and publishing plugins.
- **Plugin Runtime** (`lbp rt`) — the host process that discovers, installs and
  runs plugins, bridging them to LangBot over stdio or WebSocket.
- **Box Runtime** (`lbp box`) — the code-sandbox service backing LangBot's Box
  subsystem, executing untrusted code via Docker / nsjail / E2B backends.

LangBot depends on this package as the pinned `langbot-plugin==<x.y.z>` in its
`pyproject.toml`; the canonical version lives in this repo's `pyproject.toml`.

> The **Runtime** component (`src/langbot_plugin/runtime/`) is licensed
> separately under **AGPL**; everything else in this repository is **Apache 2.0**.
> See [`src/langbot_plugin/runtime/README.md`](src/langbot_plugin/runtime/README.md).

## Install

```bash
pip install langbot-plugin
# or, recommended
uv tool install langbot-plugin

lbp --help
```

## CLI at a glance

| Command | Purpose |
| --- | --- |
| `lbp init <name>` | Scaffold a new plugin project |
| `lbp comp <Type>` | Generate a component (Command / Tool / EventListener / KnowledgeEngine / Parser / Page) |
| `lbp run` | Run / remote-debug a plugin against a running LangBot |
| `lbp build` | Package the plugin into a distributable zip |
| `lbp publish` | Publish to the LangBot Plugin Market |
| `lbp login` / `lbp logout` | Authenticate with your LangBot account |
| `lbp rt` | Launch a standalone Plugin Runtime (control `5400`, debug `5401`) |
| `lbp box` | Launch a standalone Box sandbox runtime (default port `5410`) |
| `lbp ver` | Print the CLI / package version |

## Component types

Plugins extend LangBot through six component types, scaffolded with
`lbp comp <Type>`:

- **Command** — user-triggered actions (e.g. `!weather tokyo`)
- **Tool** — LLM-callable functions for AI agents
- **EventListener** — handlers for message-pipeline events
- **KnowledgeEngine** — custom knowledge-base retrieval for RAG
- **Parser** — custom message / content parsing
- **Page** — custom web page embedded in the LangBot admin panel

## Documentation

- Plugin development tutorial — https://docs.langbot.app/zh/plugin/dev/tutor
- Debugging the Runtime / CLI / SDK — https://docs.langbot.app/zh/develop/plugin-runtime
- Dev environment setup — https://docs.langbot.app/zh/develop/dev-config

---

## 简介（中文）

此仓库是支撑 LangBot **插件系统**与**代码沙箱**的共享基础设施，以单一的
[`langbot-plugin`](https://pypi.org/project/langbot-plugin/) 包发布到 PyPI，包含三部分：

- **插件 SDK 与 CLI**（`lbp`）—— 插件开发的 Python API、基类，以及用于脚手架、
  构建、调试和发布插件的 `lbp` 命令。
- **插件运行时**（`lbp rt`）—— 负责发现、安装并运行插件的宿主进程，通过 stdio
  或 WebSocket 与 LangBot 通信。
- **Box 运行时**（`lbp box`）—— 支撑 LangBot Box 子系统的代码沙箱服务，通过
  Docker / nsjail / E2B 后端执行不受信任的代码。

LangBot 通过 `pyproject.toml` 中固定的 `langbot-plugin==<x.y.z>` 依赖此包；
版本号以本仓库的 `pyproject.toml` 为准。

> **运行时**组件（`src/langbot_plugin/runtime/`）单独采用 **AGPL** 许可证，
> 本仓库其余部分采用 **Apache 2.0**，详见
> [`src/langbot_plugin/runtime/README.md`](src/langbot_plugin/runtime/README.md)。

更多关于使用、原理和教程，请参阅
[LangBot 插件文档](https://docs.langbot.app/zh/plugin/dev/tutor)。
