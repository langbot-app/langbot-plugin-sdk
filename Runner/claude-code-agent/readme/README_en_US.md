# Claude Code Agent

## Overview

Run Claude Code CLI as a LangBot Runner.

## Package information

- **Runner ID**: `plugin:langbot-team/ClaudeCodeAgent/default`
- **Version**: `0.1.3`
- **Repository**: [https://github.com/langbot-app/langbot-plugins/tree/main/Runner/claude-code-agent](https://github.com/langbot-app/langbot-plugins/tree/main/Runner/claude-code-agent)

## Capabilities

- **Enabled**: `streaming`, `tool calling`, `knowledge retrieval`, `steering`
- **Not declared**: `multimodal input`, `interrupt`

## Configuration

| Field | Type | Required | Default |
| --- | --- | --- | --- |
| `daemon-enabled` | `boolean` | No | false |
| `daemon-host` | `string` | No | `127.0.0.1` |
| `daemon-port` | `integer` | No | `8767` |
| `daemon-token` | `secret` | No | Empty |
| `location` | `select` | Yes | `local` |
| `workspace` | `string` | No | Empty |
| `advanced-settings` | `boolean` | No | false |
| `command` | `string` | No | `claude` |
| `args-json` | `string` | No | `[]` |
| `env-json` | `string` | No | `{}` |
| `ssh-target` | `string` | No | Empty |
| `ssh-port` | `integer` | No | `22` |
| `daemon-id` | `string` | No | Empty |
| `timeout` | `integer` | No | `300` |
| `streaming` | `boolean` | No | true |
| `reuse-session` | `boolean` | No | true |
| `dangerously-skip-permissions` | `boolean` | No | true |
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

- The runner can use only LangBot resources authorized for the current run.
- By default, Claude Code runs with `--dangerously-skip-permissions` because LangBot does not yet expose an interactive approval flow. Use it only with trusted workspaces and a constrained operating-system account. Set `dangerously-skip-permissions` to false to restore Claude Code's normal permission checks.
- Availability, model abilities, and rate limits depend on the external service.
- See the localized README files under `readme/` for translated guidance.

- Follow-ups are injected between turns, not mid-token.
- Follow-up turns currently carry text only; attachments on follow-ups are not
  yet forwarded.
- Steering only applies when the run has a conversation scope; otherwise the
  runner transparently falls back to single-turn execution.

## Structured interactions

The runner exposes a real MCP tool named `ask_user_question` through the
run-scoped LangBot MCP bridge. Its standard Claude `tool_use` event is converted
to LangBot's provider-neutral `interaction.requested` contract. The CLI process
is stopped while the user is answering. A card submission starts a new
AgentRun, resumes the same Claude Code session, and sends the answer as the next
authoritative user turn. Claude CLI must complete an MCP call before persisting
a resumable session, so it cannot accept a second result for the old
`tool_use_id` after the process exits. No Python coroutine or Claude process is
kept waiting for the user.
