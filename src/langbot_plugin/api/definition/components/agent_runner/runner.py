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

                # Stream response from LLM (with run_id tracking)
                model_uuid = ctx.resources.models[0].model_id
                messages = ctx.messages

                async for chunk in api.invoke_llm_stream(model_uuid, messages):
                    yield AgentRunResult.message_delta(chunk)

                # Final message
                final_message = Message(role="assistant", content="Hello world")
                yield AgentRunResult.run_completed(message=final_message)
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
                - run_id: Unique ID for this run
                - trigger: What triggered this run
                - conversation: Launcher/sender/bot/pipeline info
                - event: Event envelope subset (for EBA)
                - actor: Who triggered the event
                - subject: What the event is about
                - messages: Historical conversation messages
                - input: User input (text, contents, message_chain, attachments)
                - resources: Authorized resources (models, tools, KBs, files, storage)
                - runtime: Host/environment info (version, query_id, trace_id, deadline)
                - config: Runner instance configuration

        Yields:
            AgentRunResult: Progress and final result events:
                - message.delta: Streaming text chunk
                - message.completed: Complete message
                - tool.call.started: Tool call initiated
                - tool.call.completed: Tool call finished
                - state.updated: State change notification
                - run.completed: Run finished successfully
                - run.failed: Run failed with error
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

                # Stream response
                chunk = MessageChunk(role="assistant", content="Response")
                yield AgentRunResult.message_delta(chunk)

                # Complete
                yield AgentRunResult.run_completed(finish_reason="stop")
            ```
        """
        pass
