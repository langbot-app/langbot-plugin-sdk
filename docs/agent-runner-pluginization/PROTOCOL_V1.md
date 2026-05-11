# AgentRunner Protocol v1

本文档固定 AgentRunner 插件协议 v1。LangBot 和 SDK/runtime 实现都应以本文档为准。

## 1. Runner ID

LangBot 侧稳定 id：

```text
plugin:{plugin_author}/{plugin_name}/{runner_name}
```

示例：

```text
plugin:langbot/local-agent/default
plugin:langbot/dify-agent/default
plugin:alice/helpdesk-agent/ticket
```

约束：

- `plugin_author`、`plugin_name` 来自插件 manifest metadata。
- `runner_name` 来自 AgentRunner component manifest metadata。
- 一个插件可以暴露多个 runner。

## 2. Component Manifest

最小 manifest：

```yaml
apiVersion: langbot/v1
kind: AgentRunner
metadata:
  name: default
  label:
    en_US: Default Agent
    zh_Hans: 默认 Agent
  description:
    en_US: Default AgentRunner.
    zh_Hans: 默认 AgentRunner。
spec:
  protocol_version: "1"
  config: []
  capabilities: {}
  permissions: {}
execution:
  python:
    path: ./main.py
    attr: DefaultAgentRunner
```

`spec.config` 使用 LangBot DynamicForm schema。

## 3. Capabilities

默认值全部为 `false`。

```python
class AgentRunnerCapabilities(BaseModel):
    streaming: bool = False
    tool_calling: bool = False
    knowledge_retrieval: bool = False
    multimodal_input: bool = False
    event_context: bool = False
    platform_api: bool = False
    interrupt: bool = False
    stateful_session: bool = False
```

含义：

- `streaming`: runner 可能输出 `message.delta`
- `tool_calling`: runner 需要 tool list/detail/call
- `knowledge_retrieval`: runner 需要知识库列表或检索
- `multimodal_input`: runner 能处理 image/file/audio 等非纯文本输入
- `event_context`: runner 会读取 `ctx.event/actor/subject`
- `platform_api`: runner 未来可能请求平台动作，本阶段不执行
- `interrupt`: runner 支持取消或中断
- `stateful_session`: runner 会维护外部 conversation/session state

## 4. Permissions

默认值全部为空 list。

```python
class AgentRunnerPermissions(BaseModel):
    models: list[Literal["list", "invoke", "stream", "embedding"]] = []
    tools: list[Literal["list", "detail", "call"]] = []
    knowledge_bases: list[Literal["list", "retrieve"]] = []
    storage: list[Literal["plugin", "workspace"]] = []
    files: list[Literal["config", "knowledge"]] = []
    platform_api: list[str] = []
```

权限只是 runner 请求的上限。LangBot 执行时还要结合 Pipeline/Bot 绑定范围和用户配置裁剪成 `ctx.resources`。

## 5. AgentRunContext

```python
class AgentRunContext(BaseModel):
    run_id: str
    trigger: AgentTrigger
    conversation: ConversationContext | None = None
    event: AgentEventContext | None = None
    actor: ActorContext | None = None
    subject: SubjectContext | None = None
    messages: list[Message] = []
    input: AgentInput
    params: dict[str, Any] = {}
    resources: AgentResources
    state: AgentRunState = AgentRunState()
    runtime: AgentRuntimeContext
    config: dict[str, Any] = {}
```

字段边界：
- `config`: 静态 runner 配置，来自 pipeline/runner config。
- `params`: 单次运行业务参数，只读，非持久化。
- `state`: Host 管理的 scoped 状态快照，持久化。
- `runtime.metadata`: Host/runtime 可观测性信息，非业务输入契约。

### 5.0.1 params

单次运行公开业务参数。

语义：
- JSON-safe，runner 只读
- 非持久化（不带到下一次 run）
- 不等同于 LangBot query.variables
- Host 应过滤内部变量、secrets、权限控制变量

用途：
- Workflow inputs
- Prompt variables
- Pipeline 前序 stage 生成的公开业务变量
- 用户定义变量

### 5.0.2 AgentRunState

```python
class AgentRunState(BaseModel):
    conversation: dict[str, Any] = {}
    actor: dict[str, Any] = {}
    subject: dict[str, Any] = {}
    runner: dict[str, Any] = {}
```

Host 管理的 scoped 状态快照。

语义：
- Scoped（conversation/actor/subject/runner）
- 持久化（Host 持久化并下次 run 重新加载）
- Runner 可读，通过 `state.updated` 结果请求更新

Scope 定义：
- `conversation`: 当前会话 + 当前 runner 状态。例如：外部平台 conversation/thread ID，会话级上下文。
- `actor`: 当前用户跨会话状态。例如：用户偏好、长期记忆、用户画像数据。
- `subject`: 当前群组/频道/对象状态。例如：群设置、频道上下文、共享状态。
- `runner`: Runner 实例级状态（谨慎使用）。例如：runner 级配置或缓存。

Key 命名约定：
- 使用命名空间前缀：`external.*`, `memory.*`, `config.*`, `cache.*`
- 示例：`external.conversation_id`, `external.thread_id`, `memory.summary`

重要：
- State 不是 config（静态 runner 配置）。
- State 不是 params（单次运行业务参数）。
- State 不是 runtime.metadata（Host 可观测性信息）。
- State 更新应通过 `AgentRunResult.state_updated()` 请求。

### 5.1 AgentTrigger

```python
class AgentTrigger(BaseModel):
    type: str
    source: Literal["pipeline", "event_router"] = "pipeline"
    timestamp: int | None = None
```

当前 Pipeline 使用：

```json
{"type": "message.received", "source": "pipeline"}
```

### 5.2 ConversationContext

```python
class ConversationContext(BaseModel):
    session_id: str | None = None
    conversation_id: str | None = None
    launcher_type: str | None = None
    launcher_id: str | None = None
    sender_id: str | None = None
    bot_uuid: str | None = None
    pipeline_uuid: str | None = None
```

### 5.3 AgentInput

```python
class AgentInput(BaseModel):
    text: str | None = None
    contents: list[ContentElement] = []
    message_chain: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] = []

    def to_text(self) -> str: ...
```

### 5.4 AgentResources

```python
class AgentResources(BaseModel):
    models: list[ModelResource] = []
    tools: list[ToolResource] = []
    knowledge_bases: list[KnowledgeBaseResource] = []
    files: list[FileResource] = []
    storage: StorageResource = StorageResource()
    platform_capabilities: dict[str, Any] = {}
```

Resource 只表示“可见和可请求”。真正调用时 LangBot host 仍必须校验。

### 5.5 AgentRuntimeContext

```python
class AgentRuntimeContext(BaseModel):
    langbot_version: str | None = None
    sdk_protocol_version: str = "1"
    query_id: int | None = None
    trace_id: str | None = None
    deadline_at: int | None = None
    metadata: dict[str, Any] = {}
```

## 6. AgentRunResult

```python
class AgentRunResult(BaseModel):
    type: Literal[
        "message.delta",
        "message.completed",
        "tool.call.started",
        "tool.call.completed",
        "state.updated",
        "run.completed",
        "run.failed",
        "action.requested",
    ]
    data: dict[str, Any] = {}
```

### 6.1 message.delta

```json
{
  "type": "message.delta",
  "data": {
    "chunk": {
      "role": "assistant",
      "content": "partial text"
    }
  }
}
```

LangBot 映射为 `MessageChunk`。

### 6.2 message.completed

```json
{
  "type": "message.completed",
  "data": {
    "message": {
      "role": "assistant",
      "content": "final text"
    }
  }
}
```

LangBot 映射为 `Message`。

### 6.3 tool.call.started

```json
{
  "type": "tool.call.started",
  "data": {
    "tool_call_id": "call_1",
    "tool_name": "weather",
    "parameters": {}
  }
}
```

当前 Pipeline 不展示，LangBot 记录 telemetry/debug。

### 6.4 tool.call.completed

```json
{
  "type": "tool.call.completed",
  "data": {
    "tool_call_id": "call_1",
    "tool_name": "weather",
    "result": {},
    "error": null
  }
}
```

当前 Pipeline 不展示，LangBot 记录 telemetry/debug。

### 6.5 state.updated

```json
{
  "type": "state.updated",
  "data": {
    "scope": "conversation",
    "key": "external.conversation_id",
    "value": "abc"
  }
}
```

Runner 请求 Host 持久化状态变更。

参数：
- `scope`: 状态 scope，必须为 `conversation`、`actor`、`subject`、`runner` 之一。默认 `conversation`（向后兼容）。
- `key`: 状态 key，应使用命名空间前缀（如 `external.conversation_id`）。
- `value`: 状态值，必须 JSON-serializable。

SDK 定义协议；LangBot host 处理实际持久化。本阶段 Host 应支持持久化，Runner 应正确使用 scope。

### 6.6 run.completed

```json
{
  "type": "run.completed",
  "data": {
    "message": {
      "role": "assistant",
      "content": "done"
    },
    "finish_reason": "stop"
  }
}
```

如果带 message，LangBot 可以映射为最终 `Message`。如果之前已经输出 `message.completed`，可以不带 message。

### 6.7 run.failed

```json
{
  "type": "run.failed",
  "data": {
    "error": "upstream timeout",
    "code": "upstream.timeout",
    "retryable": true
  }
}
```

LangBot 按当前 Pipeline 错误策略返回用户提示。

### 6.8 action.requested

```json
{
  "type": "action.requested",
  "data": {
    "action": "platform.message.edit",
    "parameters": {}
  }
}
```

本阶段不执行，只记录 telemetry。真正执行平台动作等待 EBA EventRouter 和统一平台 API。

## 7. LangBotToRuntime Actions

### 7.1 LIST_AGENT_RUNNERS

请求：

```json
{
  "include_plugins": ["langbot/local-agent"]
}
```

响应：

```json
{
  "runners": [
    {
      "plugin_author": "langbot",
      "plugin_name": "local-agent",
      "runner_name": "default",
      "manifest": {}
    }
  ]
}
```

### 7.2 RUN_AGENT

请求：

```json
{
  "plugin_author": "langbot",
  "plugin_name": "local-agent",
  "runner_name": "default",
  "context": {}
}
```

响应是流式 `AgentRunResult`。

Runtime 必须把异常转换为 `run.failed`，不得让 generator 异常直接泄漏给 LangBot。

## 8. 兼容和废弃

废弃：

- `AgentRunReturn`
- `type == chunk`
- `type == text`
- `type == tool_call`
- `type == finish`
- query 视角 context 作为主协议

允许 SDK 提供 legacy helper，但 LangBot 新实现只发送和接收 v1。
