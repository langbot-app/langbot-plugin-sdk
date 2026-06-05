# AgentRunner SDK / Runtime 实现说明

本文档面向 SDK / Runtime 维护者。它不定义 AgentRunner Protocol v1 的
schema；协议字段、结果类型、权限字面量和 Host API 语义以 LangBot 仓库的
`docs/agent-runner-pluginization/PROTOCOL_V1.md` 为准。

## SDK 负责的实现面

- `AgentRunner` 组件基类和 runner-scoped API 入口。
- AgentRunner Protocol v1 的 Pydantic 实体实现。
- `LIST_AGENT_RUNNERS` / `RUN_AGENT` runtime action 转发。
- component manifest 的 capabilities / permissions / config 读取。
- runner 组件模板和 CLI 生成入口。
- SDK 侧单测和模板示例，保证 runner 作者只看到当前协议字段。

## 源码入口

| 入口 | 责任 |
| --- | --- |
| `src/langbot_plugin/api/definition/components/agent_runner/runner.py` | `AgentRunner` 基类、`get_run_api(ctx)`、插件实例边界。 |
| `src/langbot_plugin/api/entities/builtin/agent_runner/` | SDK Pydantic 实体实现。 |
| `src/langbot_plugin/api/proxies/agent_run_api.py` | run-scoped Host API proxy。 |
| `src/langbot_plugin/runtime/plugin/mgr.py` | runner discovery 与 `RUN_AGENT` 转发。 |
| `src/langbot_plugin/runtime/io/handlers/control.py` | LangBot -> Runtime action handler。 |
| `src/langbot_plugin/assets/templates/components/agent_runner/` | runner scaffold 模板。 |

## 同步流程

1. 协议合同变化先更新 LangBot canonical spec。
2. SDK 实体、Runtime、模板和测试按 canonical spec 同步。
3. runner 示例必须只引用 LangBot canonical spec 中的当前字段和稳定 result types。
4. SDK Runtime 把插件异常转换为 `run.failed`，不能把 generator 异常直接暴露给 Host。
5. 一个插件可以暴露多个 AgentRunner component，Runtime discovery 不得限制为单 runner。

## 高价值测试

- `AgentRunContext` 最小字段 validate。
- `AgentRunResult` 所有稳定 result type validate。
- capabilities / permissions / context policy 默认值。
- 单插件多 AgentRunner discovery。
- `RUN_AGENT` 成功流式输出。
- `RUN_AGENT` 插件异常、runner 不存在、context schema 错误 -> `run.failed`。
- 模板和 README 示例不出现旧协议字段。

## 不在本文维护

- Host 内部 `AgentBinding` / `AgentEventEnvelope` / Store 设计。
- Pipeline adapter 长期产品形态。
- 官方 runner 插件迁移计划。
- QA smoke 和实现进度。

这些内容在 LangBot 仓库的 agent-runner-pluginization 文档集中维护。
