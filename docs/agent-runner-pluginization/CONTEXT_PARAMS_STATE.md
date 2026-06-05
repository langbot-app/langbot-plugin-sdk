# AgentRunContext params 和 scoped state 语义（历史记录）

> 状态：Archived design note。本文只保留早期 `params` / scoped state 讨论的结论和取舍，不再作为 SDK 实现或 runner 作者参考。
>
> 当前事实源：
>
> - 协议 schema：`PROTOCOL_V1.md`
> - SDK 实体：`src/langbot_plugin/api/entities/builtin/agent_runner/context.py`
> - runner scaffold：`src/langbot_plugin/assets/templates/components/agent_runner/`

## 当前结论

当前 `AgentRunContext` 不包含顶层 `params` 字段，也不包含 `messages` 或 `bootstrap` 字段。

runner 应从当前字段读取输入和能力：

- `ctx.event`: 当前 trigger 的事件 envelope。
- `ctx.input`: 当前事件输入，包括文本、content elements、附件 / artifact 引用。
- `ctx.delivery`: Host 输出 surface 与 delivery capabilities。
- `ctx.resources`: run-scoped 已授权资源。
- `ctx.context`: Host inline policy 与可用 pull API。
- `ctx.state`: Host 管理的 scoped state snapshot。
- `ctx.runtime`: Host/runtime metadata。
- `ctx.config`: 当前 Agent/runner binding config。
- `ctx.adapter`: Pipeline adapter 等入口的非核心元数据；不承载核心 Agent 语义。

conversation history 不由 Host 作为 `ctx.messages` 或 `ctx.bootstrap` 内联下发。runner 如果需要历史，应根据 `ctx.context.available_apis` 通过 run-scoped history API 拉取，并在 runner 内部完成裁剪、摘要或压缩。

## 为什么废弃 `params`

早期设计曾考虑把单次运行的业务参数放入顶层 `params`，用于 Dify workflow inputs、Prompt variables、Pipeline 前序 stage 输出等场景。

当前协议没有采用这个字段，原因是：

- 单次输入应优先进入 `ctx.event` / `ctx.input`，避免和静态 `ctx.config`、持久 `ctx.state` 混淆。
- Pipeline adapter 产生的过渡元数据可以放在 `ctx.adapter.extra`，但不应成为跨 runner 的核心协议字段。
- 不同 runner 的平台特定输入应由 runner 自己的 config schema、event projection 或授权 pull API 表达，避免在 `AgentRunContext` 顶层继续扩张。

如果后续确实需要公开单次业务参数，应重新在 Protocol v1 后续版本中定义字段、来源、过滤规则和测试，而不是复活本文旧的 `params` 草案。

## scoped state 保留的部分

scoped state 的设计方向仍保留：runner 可以读取 `ctx.state`，并通过 `AgentRunResult.state_updated(...)` 请求 Host 持久化状态。

状态 scope 仍应表达为：

- `conversation`
- `actor`
- `subject`
- `runner`

状态 key 应使用命名空间前缀，例如：

- `external.conversation_id`
- `external.session_id`
- `memory.summary`
- `config.preference`

state 是 Host-owned persistence，不是插件实例变量。插件本身应保持无状态；同一个插件进程里也不应因为多个 binding 创建多个插件实例。

## 不要再使用的旧示例

以下早期草案不属于当前协议：

```python
ctx.params["workflow_input"]
ctx.messages
ctx.bootstrap
AgentRunContext(..., params={...})
```

runner 作者看到这些旧字段时，应改为：

- 当前用户输入：`ctx.input`
- 当前事件 envelope：`ctx.event`
- runner 配置：`ctx.config`
- 历史：`AgentRunAPIProxy.history_*`
- 状态：`ctx.state` + `AgentRunResult.state_updated(...)`
- 入口 adapter 过渡信息：`ctx.adapter.extra`
