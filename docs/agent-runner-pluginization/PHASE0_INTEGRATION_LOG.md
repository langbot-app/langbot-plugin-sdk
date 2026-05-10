# AgentRunner Pluginization Phase 0 聃调记录

## 时间

2026-05-10 10:09

## 参与仓库

- **langbot-plugin-sdk**: feat/agent-runner-plugin 分支
- **LangBot**: feat/agent-runner-plugin 分支
- **langbot-agent-runner**: feat/agent-runner-plugin 分支

## 聃调配置

### Runner 选择

```
plugin:langbot/local-agent/default
```

### 输入

```
1
```

### 输出

```
[stub] Echo: 1
```

## 验证链路

```
前端选择 plugin:langbot/local-agent/default
  -> LangBot pipeline
  -> AgentRunOrchestrator
  -> SDK runtime RUN_AGENT
  -> langbot-agent-runner/local-agent DefaultAgentRunner
  -> AgentRunResult
  -> LangBot response
```

## 协议要点

### LIST_AGENT_RUNNERS 响应 (v1)

```json
{
  "runners": [
    {
      "plugin_author": "langbot",
      "plugin_name": "local-agent",
      "runner_name": "default",
      "manifest": { ... },
      "protocol_version": "1",
      "capabilities": { ... },
      "permissions": { ... },
      "config": []
    }
  ]
}
```

### RUN_AGENT 流式响应 (v1)

```json
{
  "type": "run.completed",
  "data": {
    "message": {
      "role": "assistant",
      "content": "[stub] Echo: 1"
    },
    "finish_reason": "stop"
  }
}
```

## 结论

LangBot + SDK + runner repo Phase 0 聃调通过。

这是最小协议闭环，证明新 AgentRunner 插件化主链路可运行。

## 下一步

1. **Phase 1: 迁 Dify** - 让 dify-agent 从 stub 变成真实实现
2. **LangBot 后续项**:
   - 前端保存新格式 `ai.runner.id` / `ai.runner_config`
   - 持久化 migration
   - 模板 `ai.yaml/default-pipeline-config.json` 更新
   - proxy action 二次权限校验