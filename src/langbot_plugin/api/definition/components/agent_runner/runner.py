"""Agent Runner component definition."""
from __future__ import annotations

import abc
from typing import AsyncGenerator

from langbot_plugin.api.definition.components.base import BaseComponent
from langbot_plugin.api.entities.builtin.agent_runner import context


class AgentRunner(BaseComponent):
    """Agent Runner component base class.

    AgentRunner is responsible for processing user messages and generating responses.
    It can use LLM models, tools, and knowledge bases to generate intelligent responses.

    Unlike Tool or Command components, AgentRunner is not polymorphic -
    a plugin can only provide one AgentRunner implementation.

    Example:
        ```python
        from langbot_plugin.api.definition.components.agent_runner.runner import AgentRunner
        from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext, AgentRunReturn

        class MyAgentRunner(AgentRunner):
            async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunReturn, None]:
                # Use LLM
                response = await self.plugin.invoke_llm(
                    llm_model_uuid=self.config.get('llm_model_uuid'),
                    messages=ctx.messages + [
                        Message(role='user', content=str(ctx.user_message))
                    ]
                )

                yield AgentRunReturn(
                    type='finish',
                    message=response,
                    finish_reason='stop'
                )
        ```
    """

    __kind__ = "AgentRunner"

    @abc.abstractmethod
    async def run(
        self, ctx: context.AgentRunContext
    ) -> AsyncGenerator[context.AgentRunReturn, None]:
        """Run the agent to process a user message.

        Args:
            ctx: Agent run context containing:
                - query_id: Unique ID for this request
                - session: Session information (launcher_type, launcher_id, sender_id)
                - messages: Historical conversation messages
                - user_message: Current user message to process
                - use_funcs: Available tools the agent can use
                - extra_config: Extra configuration from pipeline config

        Yields:
            AgentRunReturn: Yields progress updates and final result:
                - type='chunk': Partial text content (for streaming output)
                - type='text': Complete text segment
                - type='tool_call': Agent is calling a tool
                - type='finish': Final response with complete message

        Example:
            ```python
            async def run(self, ctx: AgentRunContext) -> AsyncGenerator[AgentRunReturn, None]:
                # Stream response from LLM
                async for chunk in self.plugin.invoke_llm_stream(...):
                    yield AgentRunReturn(
                        type='chunk',
                        message_chunk=chunk
                    )

                # Indicate completion
                yield AgentRunReturn(
                    type='finish',
                    message=final_message,
                    finish_reason='stop'
                )
            ```
        """
        pass
