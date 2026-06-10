# AgentRunner SDK / Runtime 实现说明

本文档面向 SDK / Runtime 维护者。它不定义 AgentRunner Protocol v1 的
schema；协议字段、结果类型、permissions 字面量和 Host API 语义以 LangBot 仓库的
`docs/agent-runner-pluginization/PROTOCOL_V1.md` 为准。

## SDK 负责的实现面

- `AgentRunner` 组件基类和 runner-scoped API 入口。
- AgentRunner Protocol v1 的 Pydantic 实体实现。
- `LIST_AGENT_RUNNERS` / `RUN_AGENT` runtime action 转发。
- component manifest 的 `spec.capabilities` / `spec.permissions` / `spec.config` 读取。
- runner 组件模板和 CLI 生成入口。
- 远端 AgentRunner 执行支撑，包括 SDK 侧 daemon、run channel、工作区文件物化、
  HTTP `/run` 客户端 helper、run-scoped MCP 回传 shim 和 adapter 注册接口。
  SDK 不内置 Claude Code、Codex、Kimi Code、Pi Agent 等具体 adapter；这些由
  对应 runner/plugin 包通过 `AgentAdapter` 和 `--adapter module:attr` 提供。
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
| `src/langbot_plugin/remote/agent_runner/` | SDK 远端 AgentRunner daemon、client、channel、MCP shim。 |

## 同步流程

1. 协议合同变化先更新 LangBot canonical spec。
2. SDK 实体、Runtime、模板和测试按 canonical spec 同步。
3. runner 示例必须只引用 LangBot canonical spec 中的当前字段和稳定 result types。
4. SDK Runtime 把插件异常转换为 `run.failed`，不能把 generator 异常直接暴露给 Host。
5. 一个插件可以暴露多个 AgentRunner component，Runtime discovery 不得限制为单 runner。

## Host action 兼容

`GET_TOOL_DETAIL` / `CALL_TOOL` 现在由 SDK Runtime 转发给 LangBot Host 处理，
不再只在 SDK Runtime 本地解析。Host 必须同时支持两种调用 envelope：

- 普通插件调用不带 `run_id`，继续使用 `tool_parameters` / `tool_response`。
- AgentRunner 调用带 `run_id`，使用 `parameters` / `result`，并由 Host 按
  `caller_plugin_identity` 和 run resources 做权限校验。

发布 SDK Runtime 变更时必须确认配套 LangBot Host 已实现上述两个 shape；如果
SDK 与 Host 独立发版，先验证 Host action handler，再升级会转发 tool action 的 SDK。

## 高价值测试

- `AgentRunContext` 最小字段 validate。
- `AgentRunResult` 所有稳定 result type validate。
- manifest capabilities / permissions 和 context access 默认值。
- 单插件多 AgentRunner discovery。
- `RUN_AGENT` 成功流式输出。
- `RUN_AGENT` 插件异常、runner 不存在、context schema 错误 -> `run.failed`。
- 模板和 README 示例不出现旧协议字段。
- SDK 远端 AgentRunner daemon 能物化文件、拒绝越界路径、路由 adapter，并通过
  run channel 回传 MCP tool call。

## 不在本文维护

- Host 内部 `AgentBinding` / `AgentEventEnvelope` / Store 设计。
- Pipeline adapter 长期产品形态。
- 官方 runner 插件迁移计划。
- QA smoke 和实现进度。

这些内容在 LangBot 仓库的 agent-runner-pluginization 文档集中维护。
