# AgentRunner SDK 文档入口

本目录只保留 SDK / Runtime 实现 AgentRunner Protocol v1 所需的说明。

协议 schema 的唯一事实源在 LangBot 仓库：

- `docs/agent-runner-pluginization/PROTOCOL_V1.md`

不要在 SDK 仓库重抄 `AgentRunnerManifest`、`AgentRunContext`、`AgentRunResult`、
`AgentRunAPIProxy` 等协议数据结构。SDK 文档只能说明 SDK 如何承载这些结构、
哪些源码入口需要同步，以及历史方案为什么不再使用。

## 当前文件

| 文件 | 用途 |
| --- | --- |
| [PROTOCOL_V1.md](./PROTOCOL_V1.md) | 协议规范跳转页，指向 LangBot canonical spec 路径和 SDK 源码入口。 |
| [SDK_RUNTIME_PLAN.md](./SDK_RUNTIME_PLAN.md) | SDK / Runtime 实现维护说明，不定义协议 schema。 |

## SDK 源码入口

- `src/langbot_plugin/api/definition/components/agent_runner/`
- `src/langbot_plugin/api/entities/builtin/agent_runner/`
- `src/langbot_plugin/api/proxies/agent_run_api.py`
- `src/langbot_plugin/runtime/plugin/mgr.py`
- `src/langbot_plugin/runtime/io/handlers/control.py`
- `src/langbot_plugin/assets/templates/components/agent_runner/`

维护规则：

- 协议合同变化先改 LangBot canonical spec，再同步 SDK 实体、Runtime、模板和测试。
- SDK 文档发现与 LangBot spec 冲突时，以 LangBot spec 为准，并修正 SDK 文档或源码。
- SDK 文档只保留当前实现需要的内容，不保留历史协议草案或历史 smoke 记录。
