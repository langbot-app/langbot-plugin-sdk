from __future__ import annotations

import typing

import pydantic

from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.api.entities.builtin.provider import message as provider_message
from langbot_plugin.api.entities.builtin.provider import session as provider_session
from langbot_plugin.api.entities.builtin.pipeline import query as pipeline_query


class BaseEventModel(pydantic.BaseModel):
    """事件模型基类"""

    query: pipeline_query.Query = pydantic.Field(
        exclude=True,
        default=None,
    )
    """Only stored in LangBot process"""

    class Config:
        arbitrary_types_allowed = True


class PersonMessageReceived(BaseEventModel):
    """收到任何私聊消息时"""

    event_name: str = "PersonMessageReceived"

    launcher_type: str
    """发起对象类型(group/person)"""

    launcher_id: typing.Union[int, str]
    """发起对象ID(群号/QQ号)"""

    sender_id: typing.Union[int, str]
    """发送者ID(QQ号)"""

    message_chain: platform_message.MessageChain = pydantic.Field(
        serialization_alias="message_chain"
    )

    @pydantic.field_serializer("message_chain")
    def serialize_message_chain(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_chain", mode="before")
    def validate_message_chain(cls, v):
        return platform_message.MessageChain.model_validate(v)


class GroupMessageReceived(BaseEventModel):
    """收到任何群聊消息时"""

    event_name: str = "GroupMessageReceived"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    message_chain: platform_message.MessageChain = pydantic.Field(
        serialization_alias="message_chain"
    )

    @pydantic.field_serializer("message_chain")
    def serialize_message_chain(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_chain", mode="before")
    def validate_message_chain(cls, v):
        return platform_message.MessageChain.model_validate(v)


class PersonNormalMessageReceived(BaseEventModel):
    """判断为应该处理的私聊普通消息时触发"""

    event_name: str = "PersonNormalMessageReceived"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    text_message: str

    alter: typing.Optional[str] = None
    """修改后的消息文本"""

    reply: typing.Optional[list] = None
    """回复消息组件列表"""


class PersonCommandSent(BaseEventModel):
    """判断为应该处理的私聊命令时触发"""

    event_name: str = "PersonCommandSent"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    command: str

    params: list[str]

    text_message: str

    is_admin: bool

    alter: typing.Optional[str] = None
    """修改后的完整命令文本"""

    reply: typing.Optional[list] = None
    """回复消息组件列表"""


class GroupNormalMessageReceived(BaseEventModel):
    """判断为应该处理的群聊普通消息时触发"""

    event_name: str = "GroupNormalMessageReceived"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    text_message: str

    alter: typing.Optional[str] = None
    """修改后的消息文本"""

    reply: typing.Optional[list] = None
    """回复消息组件列表"""


class GroupCommandSent(BaseEventModel):
    """判断为应该处理的群聊命令时触发"""

    event_name: str = "GroupCommandSent"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    command: str

    params: list[str]

    text_message: str

    is_admin: bool

    alter: typing.Optional[str] = None
    """修改后的完整命令文本"""

    reply: typing.Optional[list] = None
    """回复消息组件列表"""


class NormalMessageResponded(BaseEventModel):
    """回复普通消息时触发"""

    event_name: str = "NormalMessageResponded"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    session: provider_session.Session
    """会话对象"""

    prefix: str
    """回复消息的前缀"""

    response_text: str
    """回复消息的文本"""

    finish_reason: str
    """响应结束原因"""

    funcs_called: list[str]
    """调用的函数列表"""

    reply: typing.Optional[list] = None
    """回复消息组件列表"""


class PromptPreProcessing(BaseEventModel):
    """会话中的Prompt预处理时触发"""

    event_name: str = "PromptPreProcessing"

    session_name: str

    default_prompt: list[provider_message.Message]
    """此对话的情景预设，可修改"""

    prompt: list[provider_message.Message]
    """此对话现有消息记录，可修改"""
