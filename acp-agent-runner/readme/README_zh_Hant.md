# ACP Runner

## 概覽

將任何相容 Agent Client Protocol 的程式設計代理作為 LangBot Runner 執行。

## 套件資訊

- **Runner ID**: `plugin:langbot-team/ACPRunner/default`
- **版本**: `0.1.4`
- **程式碼儲存庫**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## 主要能力

- **已啟用**: `streaming`, `tool calling`, `knowledge retrieval`, `multimodal input`, `steering`
- **未宣告**: `interrupt`

## 設定

| 欄位 | 類型 | 必填 | 預設值 |
| --- | --- | --- | --- |
| `daemon-enabled` | `boolean` | 否 | false |
| `daemon-host` | `string` | 否 | `127.0.0.1` |
| `daemon-port` | `integer` | 否 | `8766` |
| `daemon-token` | `secret` | 否 | 空 |
| `provider` | `select` | 是 | `claude-code` |
| `location` | `select` | 是 | `local` |
| `workspace` | `string` | 否 | 空 |
| `ssh-target` | `string` | 否 | 空 |
| `daemon-id` | `string` | 否 | 空 |
| `daemon-connect-timeout` | `integer` | 否 | `30` |
| `ssh-port` | `integer` | 否 | `22` |
| `ssh-identity-file` | `string` | 否 | 空 |
| `acp-command` | `string` | 否 | 空 |
| `knowledge-bases` | `knowledge-base-multi-selector` | 否 | `[]` |
| `langbot-assets-enabled` | `boolean` | 否 | true |
| `langbot-assets-mode` | `select` | 否 | `auto` |
| `langbot-assets-gateway-host` | `string` | 否 | `127.0.0.1` |
| `langbot-assets-gateway-port` | `integer` | 否 | `0` |
| `langbot-assets-gateway-public-url` | `string` | 否 | 空 |
| `langbot-assets-token-ttl` | `integer` | 否 | `3600` |
| `timeout` | `integer` | 否 | `300` |
| `reuse-session` | `boolean` | 否 | true |
| `env-json` | `text` | 否 | 空 |
| `ssh-connect-timeout` | `integer` | 否 | `10` |
| `ssh-extra-options` | `string` | 否 | 空 |
| `startup-timeout` | `integer` | 否 | `30` |
| `initialize-timeout` | `integer` | 否 | `120` |
| `create-session-if-missing` | `boolean` | 否 | true |
| `streaming` | `boolean` | 否 | true |
| `append-run-scope-prompt` | `boolean` | 否 | true |
| `mcp-servers-json` | `text` | 否 | 空 |

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
