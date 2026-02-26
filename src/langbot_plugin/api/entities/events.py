from __future__ import annotations

import typing

import pydantic

from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.api.entities.builtin.platform import events as platform_events
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

    message_event: platform_events.FriendMessage
    """原始消息事件"""

    message_chain: platform_message.MessageChain = pydantic.Field(
        serialization_alias="message_chain"
    )
    """原始消息链"""

    @pydantic.field_serializer("message_chain")
    def serialize_message_chain(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_chain", mode="before")
    def validate_message_chain(cls, v):
        return platform_message.MessageChain.model_validate(v)

    @pydantic.field_serializer("message_event")
    def serialize_message_event(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_event", mode="before")
    def validate_message_event(cls, v):
        return platform_events.FriendMessage.model_validate(v)


class GroupMessageReceived(BaseEventModel):
    """收到任何群聊消息时"""

    event_name: str = "GroupMessageReceived"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    message_event: platform_events.GroupMessage
    """原始消息事件"""

    message_chain: platform_message.MessageChain = pydantic.Field(
        serialization_alias="message_chain"
    )
    """原始消息链"""

    @pydantic.field_serializer("message_chain")
    def serialize_message_chain(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_chain", mode="before")
    def validate_message_chain(cls, v):
        return platform_message.MessageChain.model_validate(v)

    @pydantic.field_serializer("message_event")
    def serialize_message_event(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_event", mode="before")
    def validate_message_event(cls, v):
        return platform_events.GroupMessage.model_validate(v)


class _WithReplyMessageChain(BaseEventModel):
    """事件模型基类，包含回复消息链对象"""

    reply_message_chain: typing.Optional[platform_message.MessageChain] = (
        pydantic.Field(serialization_alias="reply_message_chain", default=None)
    )
    """回复消息链对象，仅在阻止默认行为时有效"""

    @pydantic.field_serializer("reply_message_chain")
    def serialize_reply_message_chain(self, v, _info):
        if v is None:
            return None
        return v.model_dump()

    @pydantic.field_validator("reply_message_chain", mode="before")
    def validate_reply_message_chain(cls, v):
        if v is None:
            return None
        return platform_message.MessageChain.model_validate(v)


class PersonNormalMessageReceived(_WithReplyMessageChain):
    """判断为应该处理的私聊普通消息时触发"""

    event_name: str = "PersonNormalMessageReceived"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    text_message: str

    message_event: platform_events.FriendMessage
    """原始消息事件"""

    message_chain: platform_message.MessageChain = pydantic.Field(
        serialization_alias="message_chain"
    )
    """原始消息链"""

    @pydantic.field_serializer("message_chain")
    def serialize_message_chain(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_chain", mode="before")
    def validate_message_chain(cls, v):
        return platform_message.MessageChain.model_validate(v)

    @pydantic.field_serializer("message_event")
    def serialize_message_event(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_event", mode="before")
    def validate_message_event(cls, v):
        return platform_events.FriendMessage.model_validate(v)

    user_message_alter: typing.Optional[
        typing.Union[
            provider_message.ContentElement, list[provider_message.ContentElement], str
        ]
    ] = pydantic.Field(default=None)
    """修改后的 LLM 消息对象，可用于改写用户消息"""


class GroupNormalMessageReceived(_WithReplyMessageChain):
    """判断为应该处理的群聊普通消息时触发"""

    event_name: str = "GroupNormalMessageReceived"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    text_message: str

    message_event: platform_events.GroupMessage
    """原始消息事件"""

    message_chain: platform_message.MessageChain = pydantic.Field(
        serialization_alias="message_chain"
    )

    @pydantic.field_serializer("message_chain")
    def serialize_message_chain(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_chain", mode="before")
    def validate_message_chain(cls, v):
        return platform_message.MessageChain.model_validate(v)

    @pydantic.field_serializer("message_event")
    def serialize_message_event(self, v, _info):
        return v.model_dump()

    @pydantic.field_validator("message_event", mode="before")
    def validate_message_event(cls, v):
        return platform_events.GroupMessage.model_validate(v)

    user_message_alter: typing.Optional[
        typing.Union[
            provider_message.ContentElement, list[provider_message.ContentElement], str
        ]
    ] = pydantic.Field(default=None)
    """修改后的 LLM 消息对象，可用于改写用户消息"""


class PersonCommandSent(_WithReplyMessageChain):
    """判断为应该处理的私聊命令时触发"""

    event_name: str = "PersonCommandSent"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    command: str

    params: list[str]

    text_message: str

    is_admin: bool


class GroupCommandSent(_WithReplyMessageChain):
    """判断为应该处理的群聊命令时触发"""

    event_name: str = "GroupCommandSent"

    launcher_type: str

    launcher_id: typing.Union[int, str]

    sender_id: typing.Union[int, str]

    command: str

    params: list[str]

    text_message: str

    is_admin: bool


class NormalMessageResponded(_WithReplyMessageChain):
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


class NoticeReceived(BaseEventModel):
    """收到通知事件时触发（群成员变动、禁言、撤回、戳一戳等）

    notice_type 对应 OneBot v11 的 notice_type:
        group_increase, group_decrease, group_admin, group_ban,
        group_upload, group_recall, friend_recall, friend_add, notify

    sub_type 对应各通知的子类型:
        group_increase: approve / invite
        group_decrease: leave / kick / kick_me
        group_admin: set / unset
        group_ban: ban / lift_ban
        notify: poke / lucky_king / honor
    """

    event_name: str = "NoticeReceived"

    notice_type: str
    """通知类型，如 group_increase, group_recall, notify 等。"""

    sub_type: str = ""
    """子类型，如 approve, kick, poke 等。"""

    group_id: typing.Optional[typing.Union[int, str]] = None
    """群号。"""

    user_id: typing.Optional[typing.Union[int, str]] = None
    """触发事件的用户 ID。"""

    operator_id: typing.Optional[typing.Union[int, str]] = None
    """操作者 ID。"""

    target_id: typing.Optional[typing.Union[int, str]] = None
    """目标 ID（被戳者、运气王等）。"""

    message_id: typing.Optional[typing.Union[int, str]] = None
    """关联的消息 ID（撤回事件）。"""

    duration: typing.Optional[int] = None
    """禁言时长(秒)。"""

    file: typing.Optional[dict] = None
    """文件信息(group_upload 事件)。"""

    honor_type: typing.Optional[str] = None
    """荣誉类型(notify/honor 事件)。"""


class RequestReceived(BaseEventModel):
    """收到请求事件时触发（加好友请求、加群请求、邀请入群等）

    request_type 对应 OneBot v11 的 request_type:
        friend, group

    sub_type 对应各请求的子类型 (仅 group):
        group: add / invite
    """

    event_name: str = "RequestReceived"

    request_type: str
    """请求类型: friend / group。"""

    sub_type: str = ""
    """子类型: add / invite (仅 group 请求)。"""

    user_id: typing.Optional[typing.Union[int, str]] = None
    """发送请求的用户 ID。"""

    group_id: typing.Optional[typing.Union[int, str]] = None
    """群号 (仅 group 请求)。"""

    comment: str = ""
    """验证信息/附言。"""

    flag: str = ""
    """请求 flag，用于处理请求时传入。"""


class PromptPreProcessing(BaseEventModel):
    """会话中的Prompt预处理时触发"""

    event_name: str = "PromptPreProcessing"

    session_name: str

    default_prompt: list[
        typing.Union[provider_message.Message, provider_message.MessageChunk]
    ]
    """此对话的情景预设（系统提示词），可修改"""

    prompt: list[typing.Union[provider_message.Message, provider_message.MessageChunk]]
    """此对话现有消息记录，可修改"""
