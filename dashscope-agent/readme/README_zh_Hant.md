# DashScope Agent

## 概覽

將阿里雲 DashScope 應用程式作為 LangBot Runner 執行。

## 套件資訊

- **Runner ID**: `plugin:langbot-team/DashScopeAgent/default`
- **版本**: `0.1.0`
- **程式碼儲存庫**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## 主要能力

- **已啟用**: `streaming`, `tool calling`, `knowledge retrieval`
- **未宣告**: `multimodal input`, `interrupt`

## 設定

| 欄位 | 類型 | 必填 | 預設值 |
| --- | --- | --- | --- |
| `app-type` | `select` | 是 | `agent` |
| `api-key` | `secret` | 是 | 空 |
| `app-id` | `string` | 是 | 空 |
| `references_quote` | `string` | 否 | `参考资料来自:` |
| `timeout` | `number` | 否 | `120` |
| `langbot-assets-enabled` | `boolean` | 否 | false |
| `langbot-assets-gateway-host` | `string` | 否 | `0.0.0.0` |
| `langbot-assets-gateway-port` | `integer` | 否 | `8765` |
| `langbot-assets-gateway-request-timeout` | `integer` | 否 | `60` |
| `langbot-assets-token-ttl` | `integer` | 否 | `3600` |
| `langbot-assets-input-name` | `string` | 否 | `langbot_asset_run_token` |

## Host 權限

- **`tools`**: `detail`, `call`
- **`knowledge_bases`**: `retrieve`
- **`history`**: `page`
- **`storage`**: `plugin`

## 安裝與使用

1. 從 LangBot 外掛市場安裝此外掛。
2. 在 Pipeline 的 Runner 選擇器中選取下方 Runner ID。
3. 依照設定表填入連線資訊；密鑰欄位請使用管理介面保存。

## 安全與限制

- Runner 只能使用本次執行授權的 LangBot 資源。
- 外部服務的可用性、模型能力與速率限制由對應平台決定。
- 完整行為、進階設定與產品特定限制請參閱根目錄中文 README 或英文 README_en_US.md。
