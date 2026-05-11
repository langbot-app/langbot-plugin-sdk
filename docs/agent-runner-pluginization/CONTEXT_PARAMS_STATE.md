# AgentRunContext params 和 scoped state 语义

本文档详细说明 AgentRunner Protocol v1 中 `params` 和 `state` 的语义、边界和使用方式。

## 概述

Protocol v1 引入两个新字段避免协议 drift：

- `params`: 单次运行公开业务参数
- `state`: Host 管理的 scoped 状态快照

这两个字段解决了不同 runner 实现（Dify、local、coze、n8n 等）可能引入平台特定字段的问题。

## 字段边界

### AgentRunContext 四个类似字段

| 字段 | 来源 | 持久性 | 读写 | 用途 |
|------|------|--------|------|------|
| `config` | Pipeline/Runner 配置 | 静态不变 | Runner 可读（Host 在初始化时写入） | Runner 实例配置 |
| `params` | Pipeline 前序 stage 或用户输入 | 非持久化 | Runner 只读 | 单次运行业务参数 |
| `state` | Host 持久存储 | 持久化 | Runner 可读/请求更新 | Runner scoped 状态 |
| `runtime.metadata` | Host/Runtime | 不持久化 | Runner 只读 | 可观测性信息（query_id、trace_id 等） |

### 为什么需要 params

Runner 可能需要接收单次运行的业务参数，例如：
- Workflow inputs（Dify workflow 输入变量）
- Prompt variables（注入到 prompt 的变量）
- Pipeline 前序 stage 生成的公开业务变量
- 用户定义的运行参数

这些参数：
- 不应该是 `config`：config 是静态的，不会每次运行变化
- 不应该是 `state`：params 是非持久化的，下次运行不会携带
- 不等同于 LangBot `query.variables`：Host 应过滤内部变量、secrets、权限控制变量

### 为什么需要 scoped state

Runner 可能需要维护状态，例如：
- 外部平台的 conversation/thread ID（Dify conversation_id、Slack thread_ts）
- 用户长期记忆或偏好（跨会话）
- 群组/频道设置（跨用户）
- Runner 实例级缓存或配置

这些状态：
- 不应该是 `config`：config 是静态的
- 不应该是 `params`：state 是持久化的
- 需要 scope 区分：conversation（当前会话）、actor（用户）、subject（群组）、runner（实例）

## params 详细语义

### 定义

```python
params: dict[str, Any] = Field(default_factory=dict)
```

### 语义约束

1. **JSON-safe**: 所有值必须是 JSON-serializable
2. **只读**: Runner 不应修改 params
3. **非持久化**: Host 不应将 params 携带到下一次 run
4. **Host 过滤**: Host 应过滤内部变量、secrets、权限控制变量

### 用途示例

```python
# Dify workflow inputs
params = {
    "workflow_input": "user_question",
    "prompt_var": "context_summary",
}

# n8n workflow parameters
params = {
    "workflow_trigger_payload": {...},
    "node_output_from_previous_stage": {...},
}

# 用户定义参数
params = {
    "custom_temperature": 0.7,
    "response_style": "concise",
}
```

### Runner 使用方式

```python
class MyRunner(AgentRunner):
    async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunResult, None]:
        # 只读访问 params
        workflow_input = ctx.params.get("workflow_input", "")
        temperature = ctx.params.get("custom_temperature", 0.7)

        # 不应修改 params
        # ctx.params["new_key"] = "value"  # 错误：不应修改

        # 使用 params 进行业务逻辑
        ...
```

### Host 发送方式

LangBot Host 在构造 `AgentRunContext` 时：

```python
context = AgentRunContext(
    run_id="...",
    trigger=...,
    input=...,
    params={
        # 从 Pipeline 前序 stage 获取
        "workflow_input": workflow_stage_output,
        # 从用户配置获取
        "custom_temperature": runner_config.get("temperature"),
    },
    resources=...,
    state=...,
    runtime=...,
    config=...,
)
```

## state 详细语义

### AgentRunState 定义

```python
class AgentRunState(BaseModel):
    conversation: dict[str, Any] = Field(default_factory=dict)
    """当前会话 + 当前 runner 状态"""

    actor: dict[str, Any] = Field(default_factory=dict)
    """当前用户跨会话状态"""

    subject: dict[str, Any] = Field(default_factory=dict)
    """当前群组/频道/对象状态"""

    runner: dict[str, Any] = Field(default_factory=dict)
    """Runner 实例级状态（谨慎使用）"""
```

### Scope 定义

| Scope | 持久化范围 | 示例用途 |
|-------|------------|----------|
| `conversation` | 当前会话 + 当前 runner | 外部平台 conversation/thread ID，会话级上下文 |
| `actor` | 当前用户跨所有会话 | 用户偏好、长期记忆、用户画像数据 |
| `subject` | 当前群组/频道/对象 | 群设置、频道上下文、共享状态 |
| `runner` | Runner 实例级（所有会话/用户） | Runner 级配置、缓存（谨慎使用） |

### Key 命名约定

使用命名空间前缀避免冲突：

- `external.*`: 外部平台相关状态
  - `external.conversation_id`: 外部平台会话 ID
  - `external.thread_id`: 外部平台线程 ID
  - `external.user_id`: 外部平台用户 ID

- `memory.*`: 记忆相关状态
  - `memory.summary`: 会话摘要
  - `memory.preferences`: 用户偏好

- `config.*`: 配置相关状态
  - `config.model`: 当前使用模型
  - `config.language`: 语言设置

- `cache.*`: 缓存相关状态
  - `cache.last_response`: 上次响应
  - `cache.context_window`: 上下文窗口状态

### Runner 使用方式

#### 读取 state

```python
class MyRunner(AgentRunner):
    async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunResult, None]:
        # 读取 conversation scope
        external_conv_id = ctx.state.conversation.get("external.conversation_id")

        # 读取 actor scope
        user_language = ctx.state.actor.get("preferred_language", "en")

        # 读取 subject scope
        group_topic = ctx.state.subject.get("group_topic")

        # 读取 runner scope（谨慎使用）
        cache_version = ctx.state.runner.get("cache_version")
```

#### 更新 state（请求 Host 持久化）

```python
class MyRunner(AgentRunner):
    async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunResult, None]:
        # 请求更新 conversation scope
        yield AgentRunResult.state_updated(
            key="external.conversation_id",
            value="dify_conv_123",
            scope="conversation"
        )

        # 请求更新 actor scope
        yield AgentRunResult.state_updated(
            key="preferred_language",
            value="zh",
            scope="actor"
        )

        # 向后兼容：默认 scope="conversation"
        yield AgentRunResult.state_updated(
            key="external.thread_id",
            value="thread_abc"
        )
```

### Host 处理方式

LangBot Host 在：

1. **构造 context 时**：从持久存储加载 state snapshot

```python
# 从数据库或其他持久存储加载
conversation_state = await load_conversation_state(conversation_id, runner_name)
actor_state = await load_actor_state(user_id, runner_name)
subject_state = await load_subject_state(group_id, runner_name)
runner_state = await load_runner_state(runner_name)

state = AgentRunState(
    conversation=conversation_state,
    actor=actor_state,
    subject=subject_state,
    runner=runner_state,
)

context = AgentRunContext(
    ...,
    state=state,
)
```

2. **处理 state.updated 结果时**：持久化到存储

```python
# 处理 AgentRunResult
if result.type == AgentRunResultType.STATE_UPDATED:
    scope = result.data["scope"]
    key = result.data["key"]
    value = result.data["value"]

    # 根据 scope 持久化到不同存储
    if scope == "conversation":
        await save_conversation_state(conversation_id, runner_name, key, value)
    elif scope == "actor":
        await save_actor_state(user_id, runner_name, key, value)
    elif scope == "subject":
        await save_subject_state(group_id, runner_name, key, value)
    elif scope == "runner":
        await save_runner_state(runner_name, key, value)
```

## state.updated 结果

### SDK 定义

```python
@classmethod
def state_updated(
    cls,
    key: str,
    value: Any,
    scope: str = "conversation",
) -> AgentRunResult:
    """创建 state.updated 结果。

    Runner 请求 Host 持久化状态变更。

    Args:
        key: 状态 key，应使用命名空间前缀（如 external.conversation_id）
        value: 状态值，必须 JSON-serializable
        scope: 状态 scope，必须为 conversation/actor/subject/runner 之一
            默认 "conversation" 向后兼容

    Returns:
        AgentRunResult with type="state.updated"

    Raises:
        ValueError: 如果 scope 不是有效值
    """
    if scope not in VALID_STATE_SCOPES:
        raise ValueError(f"Invalid scope '{scope}'. Must be one of: {', '.join(VALID_STATE_SCOPES)}")

    return cls(
        type=AgentRunResultType.STATE_UPDATED,
        data={"scope": scope, "key": key, "value": value},
    )
```

### 向后兼容

SDK 保证向后兼容：

```python
# 旧用法：不指定 scope
yield AgentRunResult.state_updated("external.conversation_id", "abc")
# 实际 scope="conversation"

# 新用法：显式指定 scope
yield AgentRunResult.state_updated("preferred_language", "en", scope="actor")
```

### Scope 验证

SDK 验证 scope 必须为有效值：

```python
# 无效 scope 会抛出 ValueError
yield AgentRunResult.state_updated("key", "value", scope="invalid")
# ValueError: Invalid scope 'invalid'. Must be one of: conversation, actor, subject, runner
```

## 避免协议 drift

### 问题背景

不同 runner 实现（Dify、local、coze、n8n）可能引入平台特定字段：

```python
# ❌ 错误：Dify runner 引入平台特定字段
class DifyRunner(AgentRunner):
    async def run(self, ctx):
        # Dify 特定字段
        dify_conv_id = ctx.config.get("dify_conversation_id")
        inputs = ctx.config.get("inputs")

# ❌ 错误：Coze runner 引入平台特定字段
class CozeRunner(AgentRunner):
    async def run(self, ctx):
        # Coze 特定字段
        coze_conversation_id = ctx.config.get("coze_conversation_id")
        bot_id = ctx.config.get("bot_id")
```

这会导致协议 drift：每个 runner 都有自己的特定字段，Host 需要为每个 runner 定制逻辑。

### 正确做法

使用 params 和 scoped state：

```python
# ✅ 正确：Dify runner 使用标准 params 和 state
class DifyRunner(AgentRunner):
    async def run(self, ctx):
        # params: workflow inputs
        workflow_inputs = ctx.params

        # state: 外部 conversation ID
        dify_conv_id = ctx.state.conversation.get("external.conversation_id")

        # 如果需要创建新 conversation
        if not dify_conv_id:
            dify_conv_id = await self._create_conversation()
            yield AgentRunResult.state_updated(
                "external.conversation_id",
                dify_conv_id,
                scope="conversation"
            )

# ✅ 正确：Coze runner 使用标准 params 和 state
class CozeRunner(AgentRunner):
    async def run(self, ctx):
        # params: workflow inputs
        workflow_inputs = ctx.params

        # state: 外部 conversation ID
        coze_conv_id = ctx.state.conversation.get("external.conversation_id")

        # 如果需要创建新 conversation
        if not coze_conv_id:
            coze_conv_id = await self._create_conversation()
            yield AgentRunResult.state_updated(
                "external.conversation_id",
                coze_conv_id,
                scope="conversation"
            )
```

### 好处

1. **协议统一**: 所有 runner 使用相同的 params 和 state 语义
2. **Host 简化**: Host 只需要处理通用的 params/state 逻辑，不需要为每个 runner 定制
3. **Runner 可移植**: Runner 可以在不同 Host 实现之间移植
4. **测试简化**: 测试可以使用统一的 params/state 结构

## 测试覆盖

SDK 提供完整测试覆盖：

### params 测试

```python
def test_params_default_empty_dict():
    """params 默认为空 dict"""
    ctx = AgentRunContext(...)
    assert ctx.params == {}
    assert isinstance(ctx.params, dict)

def test_params_and_state_from_dict():
    """从 dict 构造 params 和 state"""
    data = {
        "run_id": "run_dict",
        "trigger": {...},
        "input": {...},
        "params": {"workflow_input": "value1"},
        "state": {"conversation": {"external.conversation_id": "conv_abc"}},
    }
    ctx = AgentRunContext.model_validate(data)
    assert ctx.params["workflow_input"] == "value1"
    assert ctx.state.conversation["external.conversation_id"] == "conv_abc"
```

### state 测试

```python
def test_state_default_factory():
    """state 默认所有 scope 为空 dict"""
    state = AgentRunState()
    assert state.conversation == {}
    assert state.actor == {}
    assert state.subject == {}
    assert state.runner == {}

def test_state_with_values():
    """state 可以有实际值"""
    state = AgentRunState(
        conversation={"external.conversation_id": "abc"},
        actor={"preferred_language": "zh"},
    )
    assert state.conversation["external.conversation_id"] == "abc"
    assert state.actor["preferred_language"] == "zh"
```

### state_updated 测试

```python
def test_state_updated_backward_compatible():
    """向后兼容：默认 scope="conversation""""
    result = AgentRunResult.state_updated("external.conversation_id", "abc")
    assert result.data["scope"] == "conversation"

def test_state_updated_with_scope():
    """显式指定 scope"""
    result = AgentRunResult.state_updated("preferred_language", "en", scope="actor")
    assert result.data["scope"] == "actor"

def test_state_updated_invalid_scope_raises():
    """无效 scope 抛出 ValueError"""
    with pytest.raises(ValueError, match="Invalid scope"):
        AgentRunResult.state_updated("key", "value", scope="invalid")
```

## 总结

AgentRunner Protocol v1 的 params 和 scoped state 语义：

1. **params**: 单次运行业务参数，只读，非持久化，JSON-safe
2. **state**: Host 管理的 scoped 状态快照，持久化，Runner 可读/请求更新
3. **四个 scope**: conversation、actor、subject、runner
4. **命名约定**: 使用命名空间前缀（external.*、memory.*、config.*、cache.*）
5. **向后兼容**: state_updated 默认 scope="conversation"
6. **避免 drift**: 不引入平台特定字段，使用标准 params/state

这确保了协议的统一性和可移植性，简化了 Host 和 Runner 的实现。