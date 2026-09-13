# Tbox Agent

## 概覽

將螞蟻 Tbox 應用程式作為 LangBot 運行器執行。

## 套件資訊

- **運行器 ID**: `plugin:langbot-team/TboxAgent/default`
- **版本**: `0.1.0`
- **程式碼儲存庫**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## 主要能力

- **已啟用**: `streaming`, `multimodal input`
- **未宣告**: `tool calling`, `knowledge retrieval`, `interrupt`

## 設定

| 欄位 | 類型 | 必填 | 預設值 |
| --- | --- | --- | --- |
| `api-key` | `secret` | 是 | 空 |
| `app-id` | `string` | 是 | 空 |
| `timeout` | `number` | 否 | `120` |

## Host 權限

- **`storage`**: `plugin`

## 安裝與使用

1. 從 LangBot 外掛市場安裝此外掛。
2. 在 Pipeline 的運行器選擇器中選取下方運行器 ID。
3. 依照設定表填入連線資訊；密鑰欄位請使用管理介面保存。

## 安全與限制

- 運行器只能使用本次執行授權的 LangBot 資源。
- 外部服務的可用性、模型能力與速率限制由對應平台決定。
- 完整行為、進階設定與產品特定限制請參閱根目錄中文 README 或英文 README_en_US.md。
