"""ACP Runner plugin entry point."""

from __future__ import annotations

from langbot_plugin.api.definition.plugin import BasePlugin
from pkg.daemon_relay import (
    agent_runtime_daemon_config_from_plugin_config,
    get_agent_runtime_daemon_hub,
)


class AcpRunnerPlugin(BasePlugin):
    """Agent Client Protocol runner plugin."""

    def __init__(self):
        super().__init__()

    async def initialize(self) -> None:
        """Initialize the plugin."""
        config = agent_runtime_daemon_config_from_plugin_config(
            self.get_config(),
            env_prefix="LANGBOT_ACP_DAEMON",
        )
        if config["enabled"]:
            await get_agent_runtime_daemon_hub("acp", error_code_prefix="acp").start(
                host=config["host"],
                port=config["port"],
                token=config["token"],
            )
