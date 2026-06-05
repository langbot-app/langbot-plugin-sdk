# AgentRunner SDK 与 Runtime 实现计划

本文档面向 SDK/runtime 实现 agent。目标是把当前 PoC 级 AgentRunner 直接切到协议 v1，而不是继续兼容旧 `AgentRunContext(query_id/session/messages/user_message/extra_config)` 和 `AgentRunReturn(type=chunk/text/finish)`。

## 1. 最终状态

SDK 提供稳定的 AgentRunner 开发接口：

- `AgentRunner` 组件基类
- `AgentRunnerCapabilities`
- `AgentRunnerPermissions`
- `AgentRunContext`
- `AgentRunResult`
- 资源描述实体：models/tools/knowledge/files/storage/platform
- runtime action：
  - `LIST_AGENT_RUNNERS`
  - `RUN_AGENT`
- plugin proxy 能力分组和权限校验输入

Runtime 负责：

- 发现一个插件内的多个 AgentRunner 组件
- 返回完整 manifest/spec 给 LangBot registry
- 执行指定 runner
- 将插件异常转换为 `run.failed`
- 以流式 generator 透传 `AgentRunResult`

## 2. 需要替换的 PoC 设计

当前 SDK 仓库已有 PoC：

- `api/definition/components/agent_runner/runner.py`
  - 文档中写着一个插件只能提供一个 AgentRunner，这需要改掉。
- `api/entities/builtin/agent_runner/context.py`
  - 上下文仍是 query 视角。
  - 返回类型仍是 `AgentRunReturn`，type 是 `chunk/text/tool_call/finish`。
- `runtime/plugin/mgr.py`
  - 已有 `list_agent_runners()` / `run_agent()`，但返回和错误仍是旧协议。
- `runtime/io/handlers/control.py`
  - 已有 action 壳，可以保留入口，改协议。

实现时不要在旧实体上小修小补。直接迁到 v1，并保留 helper 方法辅助官方插件迁移。

## 3. 目录和文件计划

建议结构：

```text
src/langbot_plugin/api/definition/components/agent_runner/
  __init__.py
  runner.py

src/langbot_plugin/api/entities/builtin/agent_runner/
  __init__.py
  capabilities.py
  context.py
  event.py
  input.py
  resources.py
  result.py
  runtime.py
```

必要修改：

- `src/langbot_plugin/api/definition/components/__init__.py`
- `src/langbot_plugin/entities/io/actions/enums.py`
- `src/langbot_plugin/runtime/io/handlers/control.py`
- `src/langbot_plugin/runtime/plugin/mgr.py`
- `src/langbot_plugin/runtime/io/handlers/plugin.py`
- `src/langbot_plugin/api/proxies/langbot_api.py`
- `src/langbot_plugin/cli/commands/gencomponent.py`
- 插件模板目录

## 4. AgentRunner 组件接口

目标接口：

```python
class AgentRunner(BaseComponent):
    __kind__ = "AgentRunner"
    __protocol_version__ = "1"

    @classmethod
    def get_capabilities(cls) -> AgentRunnerCapabilities:
        return AgentRunnerCapabilities()

    @classmethod
    def get_config_schema(cls) -> list[dict[str, Any]]:
        return []

    @classmethod
    def get_permissions(cls) -> AgentRunnerPermissions:
        return AgentRunnerPermissions()

    async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunResult, None]:
        raise NotImplementedError
```

注意：

- 一个插件可以有多个 AgentRunner 组件。
- 每个 runner 组件通过自己的 component manifest 暴露 name/config/capabilities/permissions。
- classmethod 作为 Python 侧默认值；manifest 中显式声明优先。
- `AgentRunReturn` 更名为 `AgentRunResult`。不要在新文档中继续使用 Return。

## 5. Manifest spec

AgentRunner component manifest 的 `spec` 至少支持：

```yaml
spec:
  protocol_version: "1"
  config: []
  capabilities:
    streaming: true
    tool_calling: true
    knowledge_retrieval: true
    multimodal_input: false
    event_context: true
    platform_api: false
    interrupt: false
    stateful_session: true
  permissions:
    models: ["invoke", "stream", "rerank"]
    tools: ["detail", "call"]
    knowledge_bases: ["list", "retrieve"]
    history: ["page", "search"]
    events: ["get", "page"]
    artifacts: ["metadata", "read"]
    storage: ["plugin", "workspace", "binding"]
    files: ["config", "knowledge"]
    platform_api: []
```

Runtime discovery 输出时必须包含原始 component manifest，并保证 `spec.protocol_version`、`spec.config`、`spec.capabilities`、`spec.permissions` 有默认值。

## 6. AgentRunContext v1

目标字段：

```python
class AgentRunContext(BaseModel):
    run_id: str
    trigger: AgentTrigger
    event: AgentEventContext
    conversation: ConversationContext | None = None
    actor: ActorContext | None = None
    subject: SubjectContext | None = None
    input: AgentInput
    delivery: DeliveryContext
    resources: AgentResources
    context: ContextAccess = Field(default_factory=ContextAccess)
    state: AgentRunState = Field(default_factory=AgentRunState)
    runtime: AgentRuntimeContext
    config: dict[str, Any] = Field(default_factory=dict)
    adapter: AdapterContext | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

约束：

- `run_id` 是本次 runner 调用 id。
- `trigger.type` 当前消息 Pipeline 使用 `message.received`。
- `event` 是必选事件 envelope 子集。
- `conversation` 承载会话标识和入口上下文，不承载完整历史窗口。
- `input` 是主输入，支持 text、content elements、attachments、raw message chain。
- `delivery` 描述输出 surface 与能力。
- `resources` 是 LangBot 已授权资源列表。
- `context` 描述 Host inline policy 和可用 pull API。
- `state` 是 Host 管理的 scoped 状态快照。
- `runtime` 提供 host、workspace、bot、pipeline、query、trace、deadline。
- `config` 是当前 runner 实例配置。

`messages` 不是 context 字段；runner 通过 history pull API 拉取历史。

## 7. AgentRunResult v1

目标类型：

```python
AgentRunResult.type in [
    "message.delta",
    "message.completed",
    "tool.call.started",
    "tool.call.completed",
    "state.updated",
    "run.completed",
    "run.failed",
    "action.requested",
]
```

建议实体：

```python
class AgentRunResult(BaseModel):
    run_id: str
    type: AgentRunResultType
    data: dict[str, Any] = Field(default_factory=dict)
```

便捷构造器：

```python
AgentRunResult.message_delta(run_id: str, chunk: MessageChunk)
AgentRunResult.message_completed(run_id: str, message: Message)
AgentRunResult.tool_call_started(...)
AgentRunResult.tool_call_completed(...)
AgentRunResult.state_updated(...)
AgentRunResult.run_completed(run_id: str, message: Message | None = None)
AgentRunResult.run_failed(run_id: str, error: str, code: str | None = None)
```

旧 `chunk/text/tool_call/finish` 不属于 Protocol v1。

## 8. Runtime discovery

`PluginManager.list_agent_runners(include_plugins)`：

- 过滤 include_plugins。
- 遍历 plugin.components。
- 找到 `component.manifest.kind == "AgentRunner"`。
- 返回：
  - `plugin_author`
  - `plugin_name`
  - `runner_name`
  - `manifest`
  - `protocol_version`
  - `capabilities`
  - `permissions`

不要限制一个插件只能有一个 runner。

## 9. Runtime run_agent

`PluginManager.run_agent(plugin_author, plugin_name, runner_name, context)`：

执行流程：

1. 找 plugin。
2. 找 component kind/name。
3. 校验 component initialized。
4. `AgentRunContext.model_validate(context)`。
5. 调用 `runner_instance.run(ctx)`。
6. 对每个 result 执行 `AgentRunResult.model_validate(result)`。
7. `yield result.model_dump(mode="json")`。
8. 任何异常转为：

```json
{
  "type": "run.failed",
  "data": {
    "error": "...",
    "code": "runner.exception"
  }
}
```

不得返回旧 `finish/error`。

## 10. RuntimeToPluginAction

当前 `RUN_AGENT` 是 LangBot -> Runtime -> Python object 直接调用，不一定需要 Runtime -> Plugin action。只有在 AgentRunner 需要跨进程 action 调用时才新增。

本轮建议保持现有 runtime manager 直接调用已加载 component instance 的方式，减少协议面。

## 11. LangBotAPIProxy 能力分组

现有 proxy API 很宽。AgentRunner 场景需要显式资源授权。

建议新增：

```python
class AgentRuntimeAPIProxy:
    async def list_models(ctx: AgentRunContext) -> list[ModelResource]: ...
    async def invoke_llm(ctx: AgentRunContext, model_id: str, ...): ...
    async def invoke_llm_stream(ctx: AgentRunContext, model_id: str, ...): ...
    async def list_tools(ctx: AgentRunContext) -> list[ToolResource]: ...
    async def call_tool(ctx: AgentRunContext, tool_name: str, parameters: dict): ...
    async def list_knowledge_bases(ctx: AgentRunContext) -> list[KnowledgeBaseResource]: ...
    async def retrieve_knowledge(ctx: AgentRunContext, kb_id: str, query: str, ...): ...
```

实现可先复用 `LangBotAPIProxy` 底层 action，但 action payload 必须带：

- `run_id`
- `resource_scope`
- 具体 resource id

LangBot host 侧必须二次校验。

## 12. CLI 和模板

更新 `gencomponent`：

- 支持 `AgentRunner`
- 生成 component manifest 带 `protocol_version/capabilities/permissions`
- 生成 `run()` 示例使用 v1 `AgentRunResult`
- 示例不能再使用 `AgentRunReturn`

更新 plugin 模板：

- 可选创建 AgentRunner 组件
- README 示例展示多 runner 组件

## 13. 测试要求

SDK 单测：

- `AgentRunContext` 最小字段 validate
- `AgentRunResult` 每个类型 validate
- capabilities / permissions 默认值
- AgentRunner manifest 多组件 discovery
- `run_agent` 成功流式输出
- `run_agent` 插件异常 -> `run.failed`
- 旧 `AgentRunReturn` 不再出现在新示例和 docs

Runtime 集成测试：

- 单插件多 AgentRunner 组件都能 list
- include_plugins 正确过滤
- runner 不存在返回 `run.failed`
- context schema 错误返回 `run.failed`

## 14. 验收标准

- SDK 导出的 AgentRunner API 是 v1 context/result。
- Runtime `LIST_AGENT_RUNNERS` 输出包含 capabilities/permissions/config/protocol。
- Runtime `RUN_AGENT` 只输出 v1 `AgentRunResult`。
- 一个插件可以声明多个 AgentRunner。
- 官方 runner 插件可以只依赖 SDK v1 完成开发。
