"""Agent Runner entities for Protocol v1."""

from langbot_plugin.api.entities.builtin.agent_runner.capabilities import (
    AgentRunnerCapabilities,
)
from langbot_plugin.api.entities.builtin.agent_runner.permissions import (
    AgentRunnerPermissions,
)
from langbot_plugin.api.entities.builtin.agent_runner.trigger import AgentTrigger
from langbot_plugin.api.entities.builtin.agent_runner.input import AgentInput
from langbot_plugin.api.entities.builtin.agent_runner.resources import (
    AgentResources,
    ModelResource,
    ToolResource,
    KnowledgeBaseResource,
    FileResource,
    StorageResource,
)
from langbot_plugin.api.entities.builtin.agent_runner.runtime import AgentRuntimeContext
from langbot_plugin.api.entities.builtin.agent_runner.state import (
    AgentRunState,
    VALID_STATE_SCOPES,
)
from langbot_plugin.api.entities.builtin.agent_runner.event import (
    ConversationContext,
    AgentEventContext,
    ActorContext,
    SubjectContext,
)
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.result import (
    AgentRunResult,
    AgentRunResultType,
)
from langbot_plugin.api.entities.builtin.agent_runner.legacy import (
    AgentRunReturn,
    create_legacy_context,
)

__all__ = [
    # v1 entities
    "AgentRunnerCapabilities",
    "AgentRunnerPermissions",
    "AgentTrigger",
    "AgentInput",
    "AgentResources",
    "ModelResource",
    "ToolResource",
    "KnowledgeBaseResource",
    "FileResource",
    "StorageResource",
    "AgentRuntimeContext",
    "AgentRunState",
    "VALID_STATE_SCOPES",
    "ConversationContext",
    "AgentEventContext",
    "ActorContext",
    "SubjectContext",
    "AgentRunContext",
    "AgentRunResult",
    "AgentRunResultType",
    # Legacy (deprecated)
    "AgentRunReturn",
    "create_legacy_context",
]