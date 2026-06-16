"""External tool adapters for LangBot AgentRunner components."""

from langbot_plugin.api.agent_tools.decorators import (
    AgentToolSpec,
    agent_tool,
    collect_agent_tools,
)
from langbot_plugin.api.agent_tools.asset_gateway import (
    AgentAssetGateway,
    AgentAssetGatewayRegistration,
    LANGBOT_AGENT_GATEWAY_SERVER_NAME,
    get_default_agent_asset_gateway,
)
from langbot_plugin.api.agent_tools.daemon import (
    AgentRuntimeDaemonClient,
    AgentRuntimeDaemonError,
    AgentRuntimeDaemonHub,
    LocalMCPProxy,
    agent_runtime_daemon_config_from_plugin_config,
    get_agent_runtime_daemon_hub,
    handle_agent_runtime_mcp_payload,
)
from langbot_plugin.api.agent_tools.external_tools import AgentRunExternalTools
from langbot_plugin.api.agent_tools.mcp_access import AgentRunMCPAccess
from langbot_plugin.api.agent_tools.mcp_bridge import (
    LANGBOT_AGENT_MCP_SERVER_NAME,
    AgentRunMCPBridge,
    merge_mcp_server_config,
)
from langbot_plugin.api.agent_tools.mcp_config import (
    AgentMCPReverseTunnel,
    AgentMCPServerConfig,
    reverse_tunnel_for_endpoint,
    reverse_tunnel_for_mcp_server,
)

__all__ = [
    "AgentAssetGateway",
    "AgentAssetGatewayRegistration",
    "AgentMCPReverseTunnel",
    "AgentMCPServerConfig",
    "AgentRunMCPAccess",
    "AgentRunExternalTools",
    "AgentRunMCPBridge",
    "AgentRuntimeDaemonClient",
    "AgentRuntimeDaemonError",
    "AgentRuntimeDaemonHub",
    "AgentToolSpec",
    "LANGBOT_AGENT_GATEWAY_SERVER_NAME",
    "LANGBOT_AGENT_MCP_SERVER_NAME",
    "LocalMCPProxy",
    "agent_runtime_daemon_config_from_plugin_config",
    "agent_tool",
    "collect_agent_tools",
    "get_agent_runtime_daemon_hub",
    "get_default_agent_asset_gateway",
    "handle_agent_runtime_mcp_payload",
    "merge_mcp_server_config",
    "reverse_tunnel_for_endpoint",
    "reverse_tunnel_for_mcp_server",
]
