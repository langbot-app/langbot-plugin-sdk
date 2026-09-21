"""Codex Runner plugin entry point."""

from __future__ import annotations

from langbot_plugin.api.definition.plugin import BasePlugin
from pkg.daemon_relay import (
    agent_runtime_daemon_config_from_plugin_config,
    get_agent_runtime_daemon_hub,
)


class CodexAgentPlugin(BasePlugin):
    async def initialize(self) -> None:
        config = agent_runtime_daemon_config_from_plugin_config(
            self.get_config(),
            env_prefix="LANGBOT_CODEX_DAEMON",
            default_port=8768,
        )
        if config["enabled"]:
            await get_agent_runtime_daemon_hub("codex", error_code_prefix="codex").start(
                host=config["host"],
                port=config["port"],
                token=config["token"],
            )
