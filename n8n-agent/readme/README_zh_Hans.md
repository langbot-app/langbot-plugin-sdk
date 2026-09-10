# n8n 工作流 Agent

n8n 工作流 Agent 将 n8n Webhook 工作流接入 LangBot Runner。插件把当前输入和会话标识发送到 Webhook，支持 Basic、JWT 和自定义 Header 鉴权，并可向工作流注入短期 LangBot 资产 token。

## Runner ID

`plugin:langbot-team/N8nAgent/default`

## 主要能力

- 支持任意可返回文本或 JSON 的 n8n Webhook。
- 支持无鉴权、Basic Auth、JWT 和自定义 Header。
- 支持流式或普通响应解析。
- 为外部工作流生成并持久化独立 conversation/session ID。
- 可让 n8n AI Agent 通过 MCP Client Tool 访问 LangBot 授权资源。

## 配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `webhook-url` | `string` | 是 | 空 | n8n Webhook URL |
| `auth-type` | `select` | 是 | `none` | `none`、`basic`、`jwt` 或 `header` |
| `basic-username` | `string` | 否 | 空 | Basic Auth 用户名 |
| `basic-password` | `secret` | 否 | 空 | Basic Auth 密码 |
| `jwt-secret` | `secret` | 否 | 空 | JWT 签名密钥 |
| `jwt-algorithm` | `string` | 否 | `HS256` | JWT 算法 |
| `header-name` | `string` | 否 | 空 | 自定义鉴权 Header 名称 |
| `header-value` | `secret` | 否 | 空 | 自定义鉴权 Header 值 |
| `timeout` | `integer` | 否 | `120` | Webhook 请求超时秒数 |
| `output-key` | `string` | 否 | `response` | JSON 响应中的输出字段 |
| `langbot-assets-enabled` | `boolean` | 否 | `false` | 是否启用 LangBot 资产回调 |
| `langbot-assets-gateway-host` | `string` | 否 | `0.0.0.0` | Asset Gateway 监听地址 |
| `langbot-assets-gateway-port` | `integer` | 否 | `8765` | 网关端口 |
| `langbot-assets-gateway-request-timeout` | `integer` | 否 | `60` | 网关调用超时 |
| `langbot-assets-token-ttl` | `integer` | 否 | `3600` | 运行 token 有效期 |
| `langbot-assets-input-name` | `string` | 否 | `langbot_asset_run_token` | Webhook payload 中的 token 字段名 |

## Webhook Payload 与状态

runner 会为外部系统维护独立的 conversation ID 和 session ID，不直接复用 LangBot 内部 ID。新生成的 ID 通过 Host 会话状态持久化，后续请求保持一致。Webhook 可以使用这些字段关联工作流状态。

## LangBot 资产回调

n8n 工作流应包含：

1. Webhook Trigger，并在最后一个节点完成后返回响应。
2. 使用 HTTP Streamable transport 的 MCP Client Tool，地址指向 Asset Gateway `/mcp`。
3. 连接 MCP Client Tool 的 AI Agent。
4. prompt 中从 Webhook payload 读取 token，并在每次 LangBot MCP 调用中作为 `run_token` 传入。

因为 n8n credentials 是静态的，不适合携带每次运行变化的 Header，所以推荐使用工具参数传递 `run_token`。

## 限制与安全

- n8n Cloud 需要可公开访问的 HTTPS Asset Gateway。
- 工作流必须在 Webhook 请求结束前完成资产回调。
- Basic 密码、JWT secret 和自定义 Header 值使用密钥字段。
- `output-key` 与工作流返回结构不一致时会得到空结果或解析错误。
- token 在当前运行结束后立即注销。

## 开发检查

```bash
uv run --no-sync pytest -q
uv run --no-sync ruff check .
```
