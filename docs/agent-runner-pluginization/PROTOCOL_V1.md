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
    resources: AgentResources
    runtime: AgentRuntimeContext
    config: dict[str, Any] = {}
```

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
    "key": "external_conversation_id",
    "value": "abc"
  }
}
```

本阶段只记录，不要求 LangBot 自动持久化。官方插件应优先使用 plugin storage。

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
