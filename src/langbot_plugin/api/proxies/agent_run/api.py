"""Public run-scoped AgentRunAPIProxy implementation."""

from __future__ import annotations

from langbot_plugin.api.proxies.agent_run.common import AgentRunProxyBase
from langbot_plugin.api.proxies.agent_run.context import AgentRunContextAPIMixin
from langbot_plugin.api.proxies.agent_run.ledger import AgentRunLedgerAPIMixin
from langbot_plugin.api.proxies.agent_run.resources import AgentRunResourceAPIMixin
from langbot_plugin.api.proxies.agent_run.state import AgentRunStateAPIMixin


class AgentRunAPIProxy(
    AgentRunResourceAPIMixin,
    AgentRunContextAPIMixin,
    AgentRunLedgerAPIMixin,
    AgentRunStateAPIMixin,
    AgentRunProxyBase,
):
    """Restricted API proxy for AgentRunner execution.

    The public surface stays on one object for plugin ergonomics, while the
    implementation is split by host capability boundary: resources, context
    pull, run ledger/runtime lease, and state.
    """

    pass
