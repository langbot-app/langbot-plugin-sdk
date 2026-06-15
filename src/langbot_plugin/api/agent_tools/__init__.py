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
from langbot_plugin.api.agent_tools.external_tools import AgentRunExternalTools
from langbot_plugin.api.agent_tools.mcp_bridge import (
    LANGBOT_AGENT_MCP_SERVER_NAME,
    AgentRunMCPBridge,
    merge_mcp_server_config,
)

__all__ = [
    "AgentAssetGateway",
    "AgentAssetGatewayRegistration",
    "AgentRunExternalTools",
    "AgentRunMCPBridge",
    "AgentToolSpec",
    "LANGBOT_AGENT_GATEWAY_SERVER_NAME",
    "LANGBOT_AGENT_MCP_SERVER_NAME",
    "agent_tool",
    "collect_agent_tools",
    "get_default_agent_asset_gateway",
    "merge_mcp_server_config",
]
