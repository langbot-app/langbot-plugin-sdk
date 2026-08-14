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
- run-scoped Host API helper，包括工具、知识库、历史等资源访问的权限边界。
- SDK 不内置 Claude Code、Codex、Kimi Code、Pi Agent 等具体 adapter；只保留 runner/plugin 可复用的低层 daemon relay primitives，不提供托管式通用远端 AgentRunner 产品。外部 harness 执行策略应由 runner/plugin 包负责，优先复用 ACP 这类轻量 runtime 协议。
- SDK 侧单测和模板示例，保证 runner 作者只看到当前协议字段。

## 当前分支同步状态

`dev/4.11.x` 已同步 LangBot `dev/4.11.x` 的 AgentRunner Protocol v1 与
EBA 基础实体。SDK 侧负责的当前闭环包括：

- AgentRunner component discovery、manifest capabilities / permissions validation。
- `RUN_AGENT` 转发、result sequence 注入、deadline / cancel 传播和异常到 `run.failed` 的转换。
- run-scoped Host API proxy，包括 history / event / state / resource / ledger / admin 边界。
- agent tools MCP bridge、asset gateway、skill-as-tool resource surface。
- runtime register / heartbeat、run claim / renew / release / reconcile 的基础实体与 proxy。

截至 2026-06-23，本分支仍不提供托管式 Agent Platform、daemon supervisor、
runtime wakeup channel 或跨 Host 分布式管控；这些仍由 LangBot Host / 后续产品层实现。

## 源码入口

| 入口 | 责任 |
| --- | --- |
| `src/langbot_plugin/api/definition/components/agent_runner/runner.py` | `AgentRunner` 基类、`get_run_api(ctx)`、插件实例边界。 |
| `src/langbot_plugin/api/entities/builtin/agent_runner/` | SDK Pydantic 实体实现。 |
| `src/langbot_plugin/api/proxies/agent_run/` | run-scoped Host API proxy，按 resource/context/state/ledger/admin 边界拆分。 |
| `src/langbot_plugin/runtime/plugin/mgr.py` | runner discovery 与 `RUN_AGENT` 转发。 |
| `src/langbot_plugin/runtime/io/handlers/control.py` | LangBot -> Runtime action handler。 |
| `src/langbot_plugin/assets/templates/components/agent_runner/` | runner scaffold 模板。 |

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
- run-scoped Host API helper 会携带调用方插件身份，并让 Host 进行资源授权校验。

2026-06-23 验证：

```bash
uv run pytest \
  tests/api/entities/test_events.py \
  tests/api/entities/builtin/agent_runner \
  tests/api/proxies \
  tests/api/test_agent_tools_mcp_bridge.py \
  tests/runtime/plugin/test_mgr_agent_runner.py \
  tests/runtime/test_pull_api_handlers.py \
  tests/runtime/io/handlers/test_plugin_handler.py \
  tests/test_message.py -q

uv run python scripts/check_action_consistency.py
```

结果：311 个相关测试通过；action consistency 通过，仅保留
`CommonAction.HEARTBEAT` 未在 SDK src 中注册/调用的既有警告。

## 不在本文维护

- Host 内部 `AgentBinding` / `AgentEventEnvelope` / Store 设计。
- Pipeline adapter 长期产品形态。
- 官方 runner 插件迁移计划。
- QA smoke 和实现进度。

这些内容在 LangBot 仓库的 agent-runner-pluginization 文档集中维护。
