"""Agent Runner context entities."""
from __future__ import annotations

import typing
import pydantic

from langbot_plugin.api.entities.builtin.provider import message as provider_message
from langbot_plugin.api.entities.builtin.provider import session as provider_session
from langbot_plugin.api.entities.builtin.resource import tool as resource_tool


class AgentRunContext(pydantic.BaseModel):
    """Agent run context passed to AgentRunner.run()"""

    query_id: int
    """Query ID for this request"""

    session: provider_session.Session
    """Session information"""

    messages: list[provider_message.Message]
    """Historical messages in the conversation"""

    user_message: provider_message.ContentElement
    """Current user message"""

    use_funcs: list[resource_tool.LLMTool]
    """Available tools for the agent to use"""

    extra_config: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Extra configuration from pipeline config"""

    class Config:
        arbitrary_types_allowed = True


class AgentRunReturn(pydantic.BaseModel):
    """Return value from AgentRunner.run()"""

    type: str
    """Return type: 'text' | 'chunk' | 'tool_call' | 'finish'"""

    content: typing.Optional[str] = None
    """Text content for 'text' and 'chunk' types"""

    message: typing.Optional[provider_message.Message] = None
    """Complete message for 'finish' type"""

    message_chunk: typing.Optional[provider_message.MessageChunk] = None
    """Message chunk for 'chunk' type"""

    tool_calls: typing.Optional[list[provider_message.ToolCall]] = None
    """Tool calls for 'tool_call' type"""

    finish_reason: typing.Optional[str] = None
    """Finish reason for 'finish' type: 'stop' | 'length' | 'tool_calls' | 'error'"""

    class Config:
        arbitrary_types_allowed = True
