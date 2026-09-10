# Codex Agent

## Overview

Run Codex CLI as a LangBot Runner.

## Package information

- **Runner ID**: `plugin:langbot-team/CodexAgent/default`
- **Version**: `0.1.9`
- **Repository**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## Capabilities

- **Enabled**: `streaming`, `tool calling`, `knowledge retrieval`, `steering`
- **Not declared**: `multimodal input`, `interrupt`

## Configuration

| Field | Type | Required | Default |
| --- | --- | --- | --- |
| `daemon-enabled` | `boolean` | No | false |
| `daemon-host` | `string` | No | `127.0.0.1` |
| `daemon-port` | `integer` | No | `8768` |
| `daemon-token` | `secret` | No | Empty |
| `location` | `select` | Yes | `local` |
| `workspace` | `string` | No | Empty |
| `advanced-settings` | `boolean` | No | false |
| `command` | `string` | No | `codex` |
| `args-json` | `string` | No | `[]` |
| `env-json` | `string` | No | `{}` |
| `ssh-target` | `string` | No | Empty |
| `ssh-port` | `integer` | No | `22` |
| `daemon-id` | `string` | No | Empty |
| `timeout` | `integer` | No | `1800` |
| `streaming` | `boolean` | No | true |
| `reuse-session` | `boolean` | No | true |
| `approval-policy` | `select` | No | `never` |
| `sandbox-mode` | `select` | No | `danger-full-access` |
| `knowledge-bases` | `knowledge-base-multi-selector` | No | `[]` |
| `langbot-assets-enabled` | `boolean` | No | true |
| `mcp-bridge-transport` | `select` | No | `auto` |
| `mcp-servers-json` | `string` | No | `[]` |

## Host permissions

- **`tools`**: `detail`, `call`
- **`knowledge_bases`**: `retrieve`
- **`history`**: `page`

## Installation and usage

1. Install the plugin from the LangBot plugin marketplace.
2. Select the Runner ID below in the Pipeline Runner selector.
3. Fill in connection settings from the table and store credentials in secret fields in the admin UI.

## Security and limitations

- The default configuration starts Codex with `approvalPolicy=never` and `sandbox=danger-full-access` and does not wait for interactive approval. Use the default only with trusted workspaces and a constrained operating-system account.
- The runner can use only LangBot resources authorized for the current run.
- Availability, model abilities, and rate limits depend on the external service.
- See the full Chinese README at the package root for advanced behavior and product-specific limitations.

## Structured interactions

The runner registers a real Codex app-server dynamic tool named
`ask_user_question` and also accepts Codex's native
`item/tool/requestUserInput` request. Both are converted to LangBot's
provider-neutral `interaction.requested` contract, so Lark, DingTalk, and other
delivery adapters can render the same fields and actions.

The app-server process is stopped while the user is answering. The submission
starts a new AgentRun and resumes the same Codex thread. Codex app-server does
not support replying to an old JSON-RPC tool request from a new process, so the
answer is delivered as the next authoritative user turn rather than injected
as the old tool result. This is a provider transport limitation; the interaction
is still a real model tool call and no process is kept waiting.

Codex app-server command-execution and file-change approval requests are also
converted to action-only confirmation cards. The previous turn is cancelled
while the user decides. Approval resumes the same thread and grants exactly one
matching retry; a different command or file change requires a new approval.
