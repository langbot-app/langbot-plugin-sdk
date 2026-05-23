"""Agent Runner component definition for Protocol v1."""

from __future__ import annotations

import abc
from typing import Any, AsyncGenerator

from langbot_plugin.api.definition.components.base import BaseComponent
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.result import AgentRunResult
from langbot_plugin.api.entities.builtin.agent_runner.capabilities import (
    AgentRunnerCapabilities,
)
from langbot_plugin.api.entities.builtin.agent_runner.permissions import (
    AgentRunnerPermissions,
)


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

        return AgentRunAPIProxy(
            ctx=ctx,
            plugin_runtime_handler=self.plugin.plugin_runtime_handler,
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
                - compatibility: Legacy compatibility fields

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
