<div align="center">
<img src="docs/langbot-plugin-social.png" alt="LangBot Plugin SDK" />
</div>

## LangBot Plugin Infra

This repository contains the Runtime / SDK / CLI for LangBot Plugins. More details about usage, principles, and tutorials can be found in the [LangBot Plugin Documentation](https://docs.langbot.app/zh/plugin/dev/tutor.html)

此仓库是 LangBot 插件的运行时、SDK 和 CLI。更多关于使用、原理和教程的信息，请参阅 [LangBot 插件文档](https://docs.langbot.app/zh/plugin/dev/tutor.html)。

## Remote AgentRunner Runtime

The SDK owns the reusable remote AgentRunner runtime used by external code
runners and third-party remote agents. It provides the daemon, run channel,
workspace file materialization, HTTP client helpers, and run-scoped MCP relay.

```bash
python -m langbot_plugin.remote.agent_runner \
  --adapter my_agent.remote:adapter \
  --agent my-agent \
  --base-dir /path/to/langbot-remote-workspaces
```
