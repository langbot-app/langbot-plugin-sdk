# n8n Workflow Agent

Run an n8n workflow webhook as a LangBot Runner.

## Runner ID

`plugin:langbot-team/N8nAgent/default`

## Configuration

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| webhook-url | string | yes | '' | n8n webhook URL |
| auth-type | select | yes | none | Authentication type (none/basic/jwt/header) |
| basic-username | string | no | '' | Basic auth username |
| basic-password | secret | no | '' | Basic auth password |
| jwt-secret | secret | no | '' | JWT secret |
| jwt-algorithm | string | no | HS256 | JWT algorithm |
| header-name | string | no | '' | Custom header name |
| header-value | secret | no | '' | Custom header value |
| advanced-settings | boolean | no | false | Show timeout and response mapping controls |
| timeout | integer | no | 120 | Request timeout (seconds) |
| output-key | string | no | response | Response output key |
| langbot-assets-enabled | boolean | no | false | Register a short-lived LangBot asset token for each run and inject it into the webhook payload |
| langbot-assets-gateway-host | string | no | 0.0.0.0 | Host for the local LangBot Asset Gateway |
| langbot-assets-gateway-port | integer | no | 8765 | Port for the local LangBot Asset Gateway |
| langbot-assets-gateway-request-timeout | integer | no | 60 | Timeout for individual gateway tool calls |
| langbot-assets-token-ttl | integer | no | 3600 | Lifetime of each run token in seconds |
| langbot-assets-input-name | string | no | langbot_asset_run_token | Webhook payload field that receives the run token |

## LangBot Asset Callback Through n8n MCP Client Tool

n8n can call back into LangBot assets through the SDK Asset Gateway, the same
mechanism the Dify runner uses. The gateway is a run-token-authorized MCP server
(`POST /mcp`, JSON-RPC) that exposes the run-authorized LangBot tools:
`langbot_list_assets`, `langbot_get_current_event`, `langbot_history_page`,
`langbot_retrieve_knowledge`, `langbot_get_tool_detail`, and `langbot_call_tool`.

### How it works

1. When `langbot-assets-enabled` is true, this runner registers a short-lived,
   run-scoped token before calling the webhook and injects it into the webhook
   payload under `langbot-assets-input-name` (default `langbot_asset_run_token`).
2. The n8n workflow consumes the webhook, reads that field, and passes it as the
   `run_token` argument on every LangBot MCP tool call.
3. The runner removes the token when the run ends. Tool calls without a valid
   token are rejected by the gateway.

The gateway accepts the token either via an `Authorization: Bearer` header or via
a `run_token` tool-call argument. Because n8n credentials are static and cannot
carry a per-run header, use the **`run_token` argument** approach (same as Dify).

### Build the n8n workflow

The n8n workflow behind the webhook must use an **AI Agent** node with an
**MCP Client Tool** node attached:

1. **Webhook** trigger node — receives the LangBot payload, including
   `langbot_asset_run_token`. Respond when the last node finishes so the asset
   callbacks happen inside the request window (before the token is revoked).
2. **MCP Client Tool** node (n8n version >= 1.2, `defaultVersion` 1.3):
   - Transport: **HTTP Streamable**.
   - Endpoint: the public URL that routes to the gateway `/mcp`, e.g.
     `https://example.com/mcp`.
   - Authentication: **None** (the token travels as a tool argument, not a header).
3. **AI Agent** node — attach the MCP Client Tool. In the system prompt, instruct
   the agent to pass `run_token` on every LangBot tool call, for example:

   ```text
   For every LangBot MCP tool call, set run_token exactly to:
   {{ $json.langbot_asset_run_token }}
   Call langbot_list_assets first when you need to discover available LangBot
   assets for the current run.
   ```

4. Return the agent output in the webhook response (streaming `type: item`/`end`
   chunks, or a JSON object keyed by `output-key`).

### Configure LangBot

Select the n8n runner on the LangBot pipeline and set:

```text
webhook-url = <your n8n webhook URL>
auth-type = none
timeout = 120
langbot-assets-enabled = true
langbot-assets-gateway-host = 0.0.0.0
langbot-assets-gateway-port = 8765
langbot-assets-gateway-request-timeout = 60
langbot-assets-token-ttl = 3600
langbot-assets-input-name = langbot_asset_run_token
```

The public MCP endpoint configured in the n8n MCP Client Tool node must route to
this same gateway instance. The runner only injects the short-lived token into
the webhook payload; it does not create or update the n8n MCP Client Tool node.

### Limitations

- n8n Cloud (and any n8n that cannot reach `localhost`) needs a public HTTPS URL
  for the gateway `/mcp` endpoint. Temporary tunnel URLs are for testing only.
- The run token is short-lived and run-scoped, injected only while LangBot calls
  the webhook and revoked when the run finishes. The workflow must complete its
  asset callbacks within the webhook request.
- The gateway exposes only the assets permitted by the current run: current
  event, history page, knowledge retrieval, tool detail, and tool call.
- n8n's MCP Client Tool uses the official MCP SDK (`StreamableHTTPClientTransport`).
  Verify the `initialize` + `tools/list` handshake against your gateway once when
  setting it up.

## Legacy Runner

Migrated from `n8n-service-api` in LangBot.
