# Coze Agent

Run a Coze bot as a LangBot Runner.

## Runner ID

`plugin:langbot-team/CozeAgent/default`

## Configuration

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| api-key | secret | yes | '' | Coze API key |
| bot-id | string | yes | '' | Bot ID |
| api-base | select | yes | https://api.coze.cn | API base URL (CN or Global) |
| auto-save-history | boolean | no | true | Auto-save conversation history |
| timeout | number | no | 120 | Request timeout (seconds) |
| langbot-assets-enabled | boolean | no | false | Register a short-lived LangBot asset token for each run and pass it via custom_variables |
| langbot-assets-gateway-host | string | no | 0.0.0.0 | Host for the local LangBot Asset Gateway |
| langbot-assets-gateway-port | integer | no | 8765 | Port for the local LangBot Asset Gateway |
| langbot-assets-gateway-request-timeout | integer | no | 60 | Timeout for individual gateway tool calls |
| langbot-assets-token-ttl | integer | no | 3600 | Lifetime of each run token in seconds |
| langbot-assets-input-name | string | no | langbot_asset_run_token | custom_variables key that receives the run token |

## Capabilities

- `streaming`: yes
- `multimodal_input`: yes

## LangBot Asset Callback Through Coze MCP

A Coze bot can call back into LangBot assets through the SDK Asset Gateway, the
same mechanism the Dify runner uses. The gateway is a run-token-authorized MCP
server (`POST /mcp`, JSON-RPC) exposing the run-authorized LangBot tools:
`langbot_list_assets`, `langbot_get_current_event`, `langbot_history_page`,
`langbot_retrieve_knowledge`, `langbot_get_tool_detail`, and `langbot_call_tool`.

### How it works

1. When `langbot-assets-enabled` is true, this runner registers a short-lived,
   run-scoped token before calling the bot and passes it through Coze
   `custom_variables` under the key `langbot-assets-input-name` (default
   `langbot_asset_run_token`).
2. The bot prompt references it as `{{langbot_asset_run_token}}` and passes it as
   the `run_token` argument on every LangBot MCP tool call.
3. The runner removes the token when the run ends. Tool calls without a valid
   token are rejected by the gateway.

The gateway accepts the token via an `Authorization: Bearer` header or via a
`run_token` tool-call argument. Use the **`run_token` argument** approach here.

### Configure Coze

1. Add the LangBot Asset Gateway as an MCP plugin/tool on the bot, with a URL
   routing to the gateway `/mcp` (a public HTTPS URL for Coze Cloud).
2. Declare a bot variable named `langbot_asset_run_token` (matching
   `langbot-assets-input-name`) so `custom_variables` can populate it.
3. In the bot prompt, instruct it to pass `{{langbot_asset_run_token}}` as
   `run_token` on every LangBot MCP tool call, and to call `langbot_list_assets`
   first when it needs to discover the run's assets.

### Configure LangBot

Select the Coze runner and set:

```text
api-key = <Coze API key>
bot-id = <bot id>
api-base = https://api.coze.cn
langbot-assets-enabled = true
langbot-assets-gateway-host = 0.0.0.0
langbot-assets-gateway-port = 8765
langbot-assets-token-ttl = 3600
langbot-assets-input-name = langbot_asset_run_token
```

### Limitations

- Coze Cloud cannot reach `localhost`; use a public HTTPS URL for the gateway
  `/mcp` endpoint.
- The run token is short-lived and run-scoped; the bot must complete its asset
  callbacks within the chat run.
- The gateway exposes only the assets permitted by the current run: current
  event, history page, knowledge retrieval, tool detail, and tool call.
- The bot must support attaching an external MCP tool and forwarding the
  `custom_variables` value into the tool call. Verify the `tools/list` handshake
  and end-to-end token passing in your bot before relying on it.

## Legacy Runner

Migrated from `coze-api` in LangBot.
