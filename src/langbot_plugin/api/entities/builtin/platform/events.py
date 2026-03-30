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
# Feedback Event
class FeedbackEvent(Event):
    """User feedback event (like/dislike).

    Fired when a user gives feedback (thumbs up / thumbs down) on an AI Bot
    response.  Currently only supported by the WeChat Work (WeCom) AI Bot
    adapter, but designed to be platform-agnostic so other adapters can adopt
    it in the future.

    Args:
        feedback_id: Unique feedback identifier assigned by the platform.
        feedback_type: ``1`` = like (thumbs up), ``2`` = dislike (thumbs down).
        feedback_content: Optional free-form text the user attached.
        inaccurate_reasons: Optional list of predefined "inaccurate" reason
            tags selected by the user (for dislikes).
        user_id: ID of the user who gave feedback.
        session_id: Session / conversation ID (e.g. ``"person_xxx"`` or
            ``"group_xxx"``).
        message_id: ID of the message being rated.
        stream_id: Stream ID (for streaming responses).
        source_platform_object: Raw platform-specific object, kept for
            adapter-level introspection.
    """

    type: str = "FeedbackEvent"

    feedback_id: str
    """Unique feedback identifier from the platform."""

    feedback_type: int
    """1 = like, 2 = dislike."""

    feedback_content: typing.Optional[str] = None
    """Free-form user feedback text."""

    inaccurate_reasons: typing.Optional[typing.List[str]] = None
    """Predefined inaccuracy reasons (for dislikes)."""

    user_id: typing.Optional[str] = None
    """ID of the user who submitted the feedback."""

    session_id: typing.Optional[str] = None
    """Session / conversation ID."""

    message_id: typing.Optional[str] = None
    """ID of the original message being rated."""

    stream_id: typing.Optional[str] = None
    """Stream message ID (for streaming responses)."""

    source_platform_object: typing.Optional[typing.Any] = None
    """Raw platform event object."""
