# -*- coding: utf-8 -*-
"""
此模块提供事件模型。
"""

import typing

import pydantic

from langbot_plugin.api.entities.builtin.platform import entities as platform_entities
from langbot_plugin.api.entities.builtin.platform import message as platform_message


class Event(pydantic.BaseModel):
    """事件基类。

    Args:
        type: 事件名。
    """

    type: str
    """事件名。"""

    def __repr__(self):
        return (
            self.__class__.__name__
            + "("
            + ", ".join(
                (
                    f"{k}={repr(v)}"
                    for k, v in self.__dict__.items()
                    if k != "type" and v
                )
            )
            + ")"
        )

    @classmethod
    def parse_subtype(cls, obj: dict) -> "Event":
        try:
            return typing.cast(Event, super().parse_obj(obj))
        except ValueError:
            return Event(type=obj["type"])

    @classmethod
    def get_subtype(cls, name: str) -> typing.Type["Event"]:
        try:
            return typing.cast(typing.Type[Event], super().get_subtype(name))  # type: ignore
        except ValueError:
            return Event


###############################
# Message Event
class MessageEvent(Event):
    """消息事件。

    Args:
        type: 事件名。
        message_chain: 消息内容。
    """

    type: str
    """事件名。"""
    message_chain: platform_message.MessageChain
    """消息内容。"""

    time: float | None = None
    """消息发送时间戳。"""

    source_platform_object: typing.Optional[typing.Any] = None
    """原消息平台对象。
    供消息平台适配器开发者使用，如果回复用户时需要使用原消息事件对象的信息，
    那么可以将其存到这个字段以供之后取出使用。"""


class FriendMessage(MessageEvent):
    """私聊消息。

    Args:
        type: 事件名。
        sender: 发送消息的好友。
        message_chain: 消息内容。
    """

    type: str = "FriendMessage"
    """事件名。"""
    sender: platform_entities.Friend
    """发送消息的好友。"""
    message_chain: platform_message.MessageChain
    """消息内容。"""

    def model_dump(self, **kwargs):
        return {
            "type": self.type,
            "sender": self.sender.model_dump(),
            "message_chain": self.message_chain.model_dump(),
            "time": self.time,
        }


class GroupMessage(MessageEvent):
    """群消息。

    Args:
        type: 事件名。
        sender: 发送消息的群成员。
        message_chain: 消息内容。
    """

    type: str = "GroupMessage"
    """事件名。"""
    sender: platform_entities.GroupMember
    """发送消息的群成员。"""
    message_chain: platform_message.MessageChain
    """消息内容。"""

    @property
    def group(self) -> platform_entities.Group:
        return self.sender.group

    def model_dump(self, **kwargs):
        return {
            "type": self.type,
            "sender": self.sender.model_dump(),
            "message_chain": self.message_chain.model_dump(),
            "time": self.time,
        }


###############################
# Notice Event
class NoticeEvent(Event):
    """通知事件。

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

    type: str = "NoticeEvent"

    notice_type: str = ""
    """通知类型，如 group_increase, group_recall, notify 等。"""

    sub_type: str = ""
    """子类型，如 approve, kick, poke 等。"""

    group_id: typing.Optional[typing.Union[int, str]] = None
    """群号。"""

    user_id: typing.Optional[typing.Union[int, str]] = None
    """触发事件的用户 ID。"""

    operator_id: typing.Optional[typing.Union[int, str]] = None
    """操作者 ID（如踢人者、禁言操作者、撤回操作者）。"""

    target_id: typing.Optional[typing.Union[int, str]] = None
    """目标 ID（如被戳者、运气王）。"""

    message_id: typing.Optional[typing.Union[int, str]] = None
    """关联的消息 ID（撤回事件）。"""

    duration: typing.Optional[int] = None
    """禁言时长(秒)，0 表示解除禁言。"""

    file: typing.Optional[dict] = None
    """文件信息(group_upload 事件)，包含 id, name, size, busid。"""

    honor_type: typing.Optional[str] = None
    """荣誉类型(notify/honor 事件): talkative / performer / emotion。"""

    time: float | None = None
    """事件时间戳。"""

    source_platform_object: typing.Optional[typing.Any] = None
    """原消息平台对象。"""


###############################
# Request Event
class RequestEvent(Event):
    """请求事件。

    request_type 对应 OneBot v11 的 request_type:
        friend, group

    sub_type 对应各请求的子类型 (仅 group):
        group: add / invite
    """

    type: str = "RequestEvent"

    request_type: str = ""
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

    time: float | None = None
    """事件时间戳。"""

    source_platform_object: typing.Optional[typing.Any] = None
    """原消息平台对象。"""
