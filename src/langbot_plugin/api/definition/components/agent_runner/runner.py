"""Agent Runner component definition for Protocol v1."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any, AsyncGenerator

from langbot_plugin.api.definition.components.base import BaseComponent
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.result import AgentRunResult
from langbot_plugin.api.entities.builtin.agent_runner.capabilities import (
    AgentRunnerCapabilities,
)
from langbot_plugin.api.entities.builtin.agent_runner.permissions import (
    AgentRunnerPermissions,
)

if TYPE_CHECKING:
    from langbot_plugin.api.agent_tools import AgentRunMCPBridge
    from langbot_plugin.api.proxies.agent_run_api import AgentRunAPIProxy
    from langbot_plugin.runtime.io.handler import Handler


class AgentRunner(BaseComponent):
    """Agent Runner component base class for Protocol v1.

    AgentRunner is responsible for processing user messages and generating responses.
    It can use LLM models, tools, and knowledge bases to generate intelligent responses.

    Unlike PoC design, Protocol v1 allows a plugin to have multiple AgentRunner components.
    Each runner component exposes its own manifest with name, config, capabilities, and permissions.

    Example:
        ```python
        from langbot_plugin.api.definition.components.agent_runner.runner import AgentRunner
        from langbot_plugin.api.entities.builtin.agent_runner import (
            AgentRunContext,
            AgentRunResult,
            AgentInput,
        )
        from langbot_plugin.api.entities.builtin.provider.message import Message, MessageChunk

        class MyAgentRunner(AgentRunner):
            @classmethod
            def get_capabilities(cls) -> AgentRunnerCapabilities:
                return AgentRunnerCapabilities(
                    streaming=True,
                    tool_calling=True,
                )

            async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunResult, None]:
                # Get API proxy with run_id for LLM/tool/KB calls
                api = self.get_run_api(ctx)

                # Get bootstrap messages if available (NOT core history)
                # For full history, use ctx.context.available_apis.history_page
                messages = ctx.bootstrap.messages if ctx.bootstrap else []

                # Or build messages from current input
                if not messages:
                    messages = [Message(role="user", content=ctx.input.to_text() or "")]

                # Stream response from LLM (with run_id tracking)
                model_uuid = ctx.resources.models[0].model_id

                async for chunk in api.invoke_llm_stream(model_uuid, messages):
                    yield AgentRunResult.message_delta(ctx.run_id, chunk)

                # Final message
                final_message = Message(role="assistant", content="Hello world")
                yield AgentRunResult.run_completed(ctx.run_id, message=final_message)
        ```
    """

    __kind__ = "AgentRunner"
    __protocol_version__ = "1"

    _plugin_runtime_handler: "Handler | None"
    _plugin_config: dict[str, Any]
    _plugin_identity: str | None

    def __init__(self):
        super().__init__()
        self._plugin_runtime_handler = None
        self._plugin_config = {}
        self._plugin_identity = None

    @property
    def plugin(self) -> Any:
        """AgentRunner components do not expose the legacy BasePlugin proxy."""
        raise RuntimeError(
            "AgentRunner.plugin is not available. Use self.get_run_api(ctx) for "
            "run-scoped Host APIs, ctx.config for runner binding config, and "
            "self.get_plugin_config() only for plugin-level config."
        )

    def bind_runtime(
        self,
        *,
        plugin_runtime_handler: "Handler",
        plugin_config: dict[str, Any] | None = None,
        plugin_identity: str | None = None,
    ) -> None:
        """Bind runtime-only dependencies without exposing the legacy plugin API surface."""
        self._plugin_runtime_handler = plugin_runtime_handler
        self._plugin_config = dict(plugin_config or {})
        self._plugin_identity = plugin_identity

    def get_plugin_config(self) -> dict[str, Any]:
        """Return the plugin-level config for rare runner use cases.

        Runner binding config should normally come from ``ctx.config``.
        """
        return dict(self._plugin_config)

    @property
    def plugin_identity(self) -> str | None:
        """Plugin identity in ``author/name`` form."""
        return self._plugin_identity

    def get_run_api(self, ctx: AgentRunContext) -> "AgentRunAPIProxy":
        """Get an API proxy configured with the run context.

        Use this proxy for LLM calls, tool calls, and knowledge base retrieval
        to ensure proper context tracking and resource authorization.

        Args:
            ctx: The agent run context containing run_id, runtime.query_id, and resources.

        Returns:
            AgentRunAPIProxy: API proxy with context for Host API calls.
        """
        from langbot_plugin.api.proxies.agent_run_api import AgentRunAPIProxy

        if self._plugin_runtime_handler is None:
            raise RuntimeError("AgentRunner runtime is not bound")

        return AgentRunAPIProxy(
            ctx=ctx,
            plugin_runtime_handler=self._plugin_runtime_handler,
        )

    def create_external_mcp_bridge(self, ctx: AgentRunContext) -> "AgentRunMCPBridge":
        """Create a run-scoped MCP bridge for external harnesses.

        The bridge exposes the SDK-owned AgentRunExternalTools surface and
        delegates all LangBot asset access through AgentRunAPIProxy.
        """
        from langbot_plugin.api.agent_tools import AgentRunMCPBridge

        return AgentRunMCPBridge.from_run_api(
            api=self.get_run_api(ctx),
            ctx=ctx,
        )

    @classmethod
    def get_capabilities(cls) -> AgentRunnerCapabilities:
        """Get default capabilities for this runner.

        Override to declare specific capabilities.
        Manifest spec.capabilities takes precedence if declared.
        """
        return AgentRunnerCapabilities()

    @classmethod
    def get_config_schema(cls) -> list[dict[str, Any]]:
        """Get default config schema for this runner.

        Override to declare configuration options.
        Manifest spec.config takes precedence if declared.
        """
        return []

    @classmethod
    def get_permissions(cls) -> AgentRunnerPermissions:
        """Get default permissions for this runner.

        Override to declare required permissions.
        Manifest spec.permissions takes precedence if declared.
        """
        return AgentRunnerPermissions()

    @abc.abstractmethod
    async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunResult, None]:
        """Run the agent to process user input.

        Args:
            ctx: Agent run context containing:
                - run_id: Unique ID for this run (REQUIRED for all AgentRunResult factories)
                - trigger: What triggered this run
                - conversation: Launcher/sender/bot/pipeline info
                - event: Event envelope subset (REQUIRED for Protocol v1)
                - actor: Who triggered the event
                - subject: What the event is about
                - input: User input (text, contents, message_chain, attachments)
                - delivery: Output surface capabilities (REQUIRED for Protocol v1)
                - resources: Authorized resources (models, tools, KBs, files, storage)
                - context: ContextAccess - what's inlined, what APIs are available
                - state: Host-managed scoped state snapshot
                - runtime: Host/environment info (version, query_id, trace_id, deadline)
                - config: Runner instance configuration
                - bootstrap: Optional bootstrap messages (NOT core history)
                - adapter: Pipeline adapter / host adapter metadata

        Yields:
            AgentRunResult: Progress and final result events:
                - message.delta: Streaming text chunk (use ctx.run_id)
                - message.completed: Complete message (use ctx.run_id)
                - tool.call.started: Tool call initiated (use ctx.run_id)
                - tool.call.completed: Tool call finished (use ctx.run_id)
                - state.updated: State change notification (use ctx.run_id)
                - run.completed: Run finished successfully (use ctx.run_id)
                - run.failed: Run failed with error (use ctx.run_id)
                - action.requested: Platform action request (future)

        Example:
            ```python
            async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunResult, None]:
                # Get input text
                user_text = ctx.input.to_text()

                # Use LLM (if authorized)
                if ctx.resources.models:
                    model = ctx.resources.models[0]
                    # Call LLM via plugin API...

                # Stream response - NOTE: ctx.run_id is REQUIRED
                chunk = MessageChunk(role="assistant", content="Response")
                yield AgentRunResult.message_delta(ctx.run_id, chunk)

                # Complete - NOTE: ctx.run_id is REQUIRED
                yield AgentRunResult.run_completed(ctx.run_id, finish_reason="stop")
            ```
        """
        pass
