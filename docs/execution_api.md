# ExecutionAPI 操作一览与作用域说明

LangBot Core 通过统一的 `ExecutionAPI` facade 暴露 69 项核心业务能力。插件与 Agent Runner 可以通过统一的授权契约与 SDK 入口调用这些能力。

## 作用域（Scopes）说明

ExecutionAPI 定义了严格的作用域划分，防止权限提升与越权访问：

| 作用域 | 标识 | 说明 |
| :--- | :--- | :--- |
| **Plugin** | `plugin` | 插件安装级别能力。仅在非 Run 上下文或具有插件完整 InstallationBinding 时可用。Run 上下文无法降级使用此类操作。 |
| **Run** | `run` | 单次 Agent Run 作用域。必须携带有效的 `run_id`，且在会话生命周期内严格受限，调用时自动校验该 Run 的授权范围（如 Tool、Box 等资源）。 |
| **Runner Admin** | `runner_admin` | 运行器管理级别能力（如 Run 查询、状态恢复等）。需要特定的运行器管理权限，支持根据 AgentRun 授权快照恢复过期的 Run 上下文。 |
| **Plugin or Run** | `plugin_or_run` | 双模作用域能力（如 LLM 调用、存储操作等）。在 Run 上下文中调用时携带 Run 授权与审计标识；在普通插件事件上下文调用时使用插件安装级别凭证。 |

---

## SDK 调用方式

### 1. 通用 Execution 代理入口

SDK 在 `LangBotAPIProxy` 与 `RunnerAPIProxy`（即 `ctx.api`）上提供了通用的 `execution` 入口：

```python
# 1. 单目调用 (Unary)
version_info = await api.execution.invoke("execution.get_langbot_version")
# 也可以省略 "execution." 前缀
version_info = await api.execution.invoke("get_langbot_version")

# 2. 流式调用 (Streaming)
async for chunk in api.execution.stream(
    "execution.invoke_llm_stream",
    llm_model_uuid="your-model-uuid",
    messages=[{"role": "user", "content": "Hello"}],
):
    print(chunk)
```

在 Runner 上下文中（如 `ctx.api.execution.invoke(...)`），`run_id` 会由代理自动注入，确保上下文安全传递。

### 2. Box 专用代理方法

在 `LangBotAPIProxy` 上，新增了与 Runner 一致的 Box 沙箱绑定与文件流转方法（均具备 `@run_scoped` 保护）：

- `await api.bind_box(box_id: str) -> BoxBinding`: 绑定当前运行至指定 Box 沙箱。
- `await api.import_box_attachments(attachment_ids: list[str] | None = None) -> list[BoxFile]`: 将附件导入至绑定的 Box 沙箱。
- `await api.export_box_files(paths: list[str] | None = None) -> list[BoxFile]`: 从 Box 沙箱导出生成的文件。

---

## 69 项操作完整清单

| 操作 ID (Operation ID) | 作用域 (Scope) | 副作用 (Side Effect) | 流式 (Streaming) | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| `execution.reply_message` | `plugin` | 是 | 否 | 回复消息到当前查询来源 |
| `execution.get_bot_uuid` | `plugin` | 否 | 否 | 获取当前查询关联的机器人 UUID |
| `execution.set_query_var` | `plugin` | 是 | 否 | 设置当前查询变量 |
| `execution.get_query_var` | `plugin` | 否 | 否 | 获取当前查询变量 |
| `execution.get_query_vars` | `plugin` | 否 | 否 | 获取当前查询的所有变量 |
| `execution.create_new_conversation` | `plugin` | 是 | 否 | 为当前查询创建新会话 |
| `execution.get_langbot_version` | `plugin_or_run` | 否 | 否 | 获取 LangBot Core 版本与 API 特性 |
| `execution.get_bots` | `plugin` | 否 | 否 | 获取已配置的机器人列表 |
| `execution.get_bot_info` | `plugin` | 否 | 否 | 获取指定机器人的详细信息 |
| `execution.send_message` | `plugin` | 是 | 否 | 向目标实体主动发送消息 |
| `execution.upload_file` | `plugin` | 是 | 否 | 上传文件并获取文件信息 |
| `execution.upload_file_chunk` | `plugin` | 是 | 否 | 分块上传文件数据 |
| `execution.list_files` | `plugin` | 否 | 否 | 列出当前安装下的文件 |
| `execution.delete_file` | `plugin` | 是 | 否 | 删除已上传的文件 |
| `execution.get_llm_models` | `plugin` | 否 | 否 | 列出可用 LLM 模型 UUID 列表 |
| `execution.count_tokens` | `plugin_or_run` | 否 | 否 | 计算指定消息链的 Token 数量 |
| `execution.invoke_llm` | `plugin_or_run` | 是 | 否 | 单目同步调用大语言模型 |
| `execution.invoke_llm_stream` | `plugin_or_run` | 是 | 是 | 流式调用大语言模型 |
| `execution.call_tool` | `plugin_or_run` | 是 | 否 | 调用工具（Tool）执行能力 |
| `execution.get_tool_detail` | `plugin_or_run` | 否 | 否 | 获取工具定义及参数模式 |
| `execution.get_tools` | `plugin` | 否 | 否 | 列出可用工具定义 |
| `execution.set_binary_storage` | `plugin_or_run` | 是 | 否 | 设置二进制键值存储 |
| `execution.get_binary_storage` | `plugin_or_run` | 否 | 否 | 读取二进制键值存储 |
| `execution.delete_binary_storage` | `plugin_or_run` | 是 | 否 | 删除指定键的二进制存储 |
| `execution.get_binary_storage_keys` | `plugin_or_run` | 否 | 否 | 列出二进制存储键名 |
| `execution.get_config_file` | `plugin` | 否 | 否 | 读取插件配置文件 |
| `execution.call_platform_api` | `plugin_or_run` | 是 | 否 | 调用底层平台通信 API |
| `execution.invoke_embedding` | `plugin_or_run` | 否 | 否 | 调用文本向量嵌入模型 |
| `execution.invoke_rerank` | `plugin_or_run` | 否 | 否 | 调用重排（Rerank）模型 |
| `execution.create_vector_collection` | `plugin` | 是 | 否 | 创建向量集合 |
| `execution.delete_vector_collection` | `plugin` | 是 | 否 | 删除向量集合 |
| `execution.has_vector_collection` | `plugin` | 否 | 否 | 检查向量集合是否存在 |
| `execution.vector_upsert` | `plugin` | 是 | 否 | 插入或更新向量数据 |
| `execution.vector_search` | `plugin` | 否 | 否 | 执行向量相似度检索 |
| `execution.vector_delete` | `plugin` | 是 | 否 | 删除特定向量数据 |
| `execution.retrieve_knowledge` | `plugin_or_run` | 否 | 否 | 检索指定知识库中的切片内容 |
| `execution.retrieve_knowledge_base` | `plugin_or_run` | 否 | 否 | 检索指定知识库切片（兼容入口） |
| `execution.get_prompt` | `run` | 否 | 否 | 获取当前运行预处理后的有效 Prompt |
| `execution.history_page` | `run` | 否 | 否 | 分页获取当前会话的历史交互记录 |
| `execution.event_get` | `run` | 否 | 否 | 获取特定历史事件的详情 |
| `execution.event_subscribe` | `run` | 是 | 是 | 订阅当前会话后续到达的事件流 |
| `execution.event_reply` | `run` | 是 | 否 | 向当前正在处理的事件发送答复 |
| `execution.interaction_create` | `run` | 是 | 否 | 向用户发起人机交互请求 |
| `execution.interaction_wait` | `run` | 否 | 否 | 等待交互请求结果 |
| `execution.interaction_cancel` | `run` | 是 | 否 | 取消待处理的交互请求 |
| `execution.interaction_list` | `run` | 否 | 否 | 列出当前运行发起的交互请求 |
| `execution.interaction_get` | `run` | 否 | 否 | 获取单项交互请求的状态与答复 |
| `execution.interaction_stream` | `run` | 是 | 是 | 流式监听交互请求状态变更 |
| `execution.state_get` | `run` | 否 | 否 | 获取 Agent 作用域状态值 |
| `execution.state_set` | `run` | 是 | 否 | 设置 Agent 作用域状态值 |
| `execution.state_patch` | `run` | 是 | 否 | 局部修补 Agent 状态值 |
| `execution.state_delete` | `run` | 是 | 否 | 删除 Agent 状态值 |
| `execution.get_box_status` | `plugin_or_run` | 否 | 否 | 获取 Box 沙箱服务运行状态 |
| `execution.list_boxes` | `plugin_or_run` | 否 | 否 | 列出当前工作区中可用的 Box 沙箱 |
| `execution.acquire_box` | `plugin_or_run` | 是 | 否 | 申请或复用 Box 沙箱实例 |
| `execution.bind_box` | `run` | 是 | 否 | 将特定 Box 实例与当前运行绑定 |
| `execution.import_box_attachments` | `run` | 是 | 否 | 导入附件至绑定的 Box 沙箱 |
| `execution.export_box_files` | `run` | 是 | 否 | 导出 Box 沙箱生成的文件 |
| `execution.run_get` | `runner_admin` | 否 | 否 | 管理员查询指定 Agent Run 状态 |
| `execution.run_list` | `runner_admin` | 否 | 否 | 管理员分页查询历史 Agent Run 列表 |
| `execution.run_kill` | `runner_admin` | 是 | 否 | 管理员主动终止进行中的 Agent Run |
| `execution.run_stats` | `runner_admin` | 否 | 否 | 查询工作区内 Agent Run 运行统计 |
| `execution.run_steer` | `runner_admin` | 是 | 否 | 向进行中的 Agent Run 注入控制信号 |
| `execution.run_feedback` | `runner_admin` | 是 | 否 | 提交对 Agent Run 的评价反馈 |
| `execution.reply_stream_create` | `run` | 是 | 否 | 创建增量回复流通道 |
| `execution.reply_stream_chunk` | `run` | 是 | 否 | 向回复流通道写入文本增量块 |
| `execution.reply_stream_end` | `run` | 是 | 否 | 正常终结回复流通道 |
| `execution.reply_stream_fail` | `run` | 是 | 否 | 异常终结回复流通道并记录错误 |
| `execution.reply_stream_status` | `run` | 否 | 否 | 查询回复流通道投递状态 |

---

## 内部通信/传输动作审计说明

以下 6 个底层动作属于运行时传输控制与引导动作，不对外作为业务能力暴露在 `ExecutionAPI` 中：

1. `__ping`: WebSocket 心跳保活动作。
2. `__file_chunk`: 底层文件传输协议分块帧。
3. `__stream_ack`: 流式背压确认帧。
4. `__cancel_action`: 底层通信动作取消信号。
5. `initialize_plugin_settings`: 插件安装初始配置引导。
6. `get_plugin_settings`: 插件运行时启动配置拉取。
