# -*- coding: utf-8 -*-
"""
Platform event models.
"""

import typing

import pydantic

from langbot_plugin.api.entities.builtin.platform import entities as platform_entities
from langbot_plugin.api.entities.builtin.platform import message as platform_message


class Event(pydantic.BaseModel):
    """Base event class.

    Args:
        type: Event type name.
    """

    type: str
    """Event type name."""

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
# Legacy Message Events (unchanged)
###############################

class MessageEvent(Event):
    """Message event.

    Args:
        type: Event type name.
        message_chain: Message content.
    """

    type: str
    """Event type name."""
    message_chain: platform_message.MessageChain
    """Message content."""

    time: float | None = None
    """Message timestamp."""

    source_platform_object: typing.Optional[typing.Any] = None
    """Original platform event object.
    For adapter developers: store the raw platform event here so it can be
    retrieved later when replying to the user."""


class FriendMessage(MessageEvent):
    """Private (direct) message.

    Args:
        type: Event type name.
        sender: The friend who sent the message.
        message_chain: Message content.
    """

    type: str = "FriendMessage"
    """Event type name."""
    sender: platform_entities.Friend
    """Message sender."""
    message_chain: platform_message.MessageChain
    """Message content."""

    def model_dump(self, **kwargs):
        return {
            "type": self.type,
            "sender": self.sender.model_dump(),
            "message_chain": self.message_chain.model_dump(),
            "time": self.time,
        }


class GroupMessage(MessageEvent):
    """Group message.

    Args:
        type: Event type name.
        sender: The group member who sent the message.
        message_chain: Message content.
    """

    type: str = "GroupMessage"
    """Event type name."""
    sender: platform_entities.GroupMember
    """Message sender."""
    message_chain: platform_message.MessageChain
    """Message content."""

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
# EBA Unified Event System (new)
###############################

class EBAEvent(Event):
    """EBA event base class.

    All unified EBA events inherit from this class.
    Coexists with the legacy MessageEvent hierarchy.
    """

    type: str
    """Event type identifier, e.g. 'message.received'."""

    timestamp: float = 0.0
    """Event timestamp."""

    bot_uuid: str = ""
    """UUID of the bot that received this event."""

    adapter_name: str = ""
    """Name of the adapter that produced this event."""

    source_platform_object: typing.Optional[typing.Any] = None
    """Raw platform event object for internal adapter use."""


# ---- Message Events ----

class MessageReceivedEvent(EBAEvent):
    """New message received. Replaces legacy FriendMessage / GroupMessage."""

    type: str = "message.received"

    message_id: typing.Union[int, str] = ""
    """Message ID."""

    message_chain: platform_message.MessageChain = platform_message.MessageChain([])
    """Message content."""

    sender: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))
    """Message sender."""

    chat_type: platform_entities.ChatType = platform_entities.ChatType.PRIVATE
    """Chat type."""

    chat_id: typing.Union[int, str] = ""
    """Chat ID (user ID for private chats, group ID for group chats)."""

    group: typing.Optional[platform_entities.UserGroup] = None
    """Group info (only present in group chats)."""

    def to_legacy_event(self) -> typing.Union[FriendMessage, GroupMessage]:
        """Convert this EBA event to a legacy-format event (compatibility layer)."""
        if self.chat_type == platform_entities.ChatType.PRIVATE:
            return FriendMessage(
                sender=platform_entities.Friend(
                    id=self.sender.id,
                    nickname=self.sender.nickname,
                    remark=self.sender.remark,
                ),
                message_chain=self.message_chain,
                time=self.timestamp,
                source_platform_object=self.source_platform_object,
            )
        else:
            group = platform_entities.Group(
                id=self.group.id if self.group else self.chat_id,
                name=self.group.name if self.group else "",
                permission=platform_entities.Permission.Member,
            )
            return GroupMessage(
                sender=platform_entities.GroupMember(
                    id=self.sender.id,
                    member_name=self.sender.nickname,
                    permission=platform_entities.Permission.Member,
                    group=group,
                ),
                message_chain=self.message_chain,
                time=self.timestamp,
                source_platform_object=self.source_platform_object,
            )


class MessageEditedEvent(EBAEvent):
    """Message was edited."""

    type: str = "message.edited"

    message_id: typing.Union[int, str] = ""
    """ID of the edited message."""

    new_content: platform_message.MessageChain = platform_message.MessageChain([])
    """New content after editing."""

    editor: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))
    """User who edited the message."""

    chat_type: platform_entities.ChatType = platform_entities.ChatType.PRIVATE
    chat_id: typing.Union[int, str] = ""
    group: typing.Optional[platform_entities.UserGroup] = None


class MessageDeletedEvent(EBAEvent):
    """Message was deleted / recalled."""

    type: str = "message.deleted"

    message_id: typing.Union[int, str] = ""
    """ID of the deleted message."""

    operator: typing.Optional[platform_entities.User] = None
    """User who deleted the message."""

    chat_type: platform_entities.ChatType = platform_entities.ChatType.PRIVATE
    chat_id: typing.Union[int, str] = ""
    group: typing.Optional[platform_entities.UserGroup] = None


class MessageReactionEvent(EBAEvent):
    """Message received an emoji reaction."""

    type: str = "message.reaction"

    message_id: typing.Union[int, str] = ""
    """ID of the reacted message."""

    user: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))
    """User who reacted."""

    reaction: str = ""
    """Reaction emoji identifier."""

    is_add: bool = True
    """True if reaction was added, False if removed."""

    chat_type: platform_entities.ChatType = platform_entities.ChatType.PRIVATE
    chat_id: typing.Union[int, str] = ""
    group: typing.Optional[platform_entities.UserGroup] = None


# ---- Group Events ----

class MemberJoinedEvent(EBAEvent):
    """New member joined a group."""

    type: str = "group.member_joined"

    group: platform_entities.UserGroup = pydantic.Field(default_factory=lambda: platform_entities.UserGroup(id=""))
    """The group."""

    member: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))
    """The member who joined."""

    inviter: typing.Optional[platform_entities.User] = None
    """Inviter (if applicable)."""

    join_type: typing.Optional[str] = None
    """How the member joined: 'invite' / 'request' / 'direct' / None."""


class MemberLeftEvent(EBAEvent):
    """Member left a group."""

    type: str = "group.member_left"

    group: platform_entities.UserGroup = pydantic.Field(default_factory=lambda: platform_entities.UserGroup(id=""))
    member: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))

    is_kicked: bool = False
    """Whether the member was kicked."""

    operator: typing.Optional[platform_entities.User] = None
    """Operator (the admin who kicked, if applicable)."""


class MemberBannedEvent(EBAEvent):
    """Member was muted / restricted."""

    type: str = "group.member_banned"

    group: platform_entities.UserGroup = pydantic.Field(default_factory=lambda: platform_entities.UserGroup(id=""))
    member: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))
    operator: typing.Optional[platform_entities.User] = None
    duration: typing.Optional[int] = None
    """Mute duration in seconds. None means permanent."""


class GroupInfoUpdatedEvent(EBAEvent):
    """Group info was updated."""

    type: str = "group.info_updated"

    group: platform_entities.UserGroup = pydantic.Field(default_factory=lambda: platform_entities.UserGroup(id=""))
    """Updated group info."""

    operator: typing.Optional[platform_entities.User] = None
    changed_fields: list[str] = []
    """List of field names that changed."""


# ---- Friend Events ----

class FriendRequestReceivedEvent(EBAEvent):
    """Friend request received."""

    type: str = "friend.request_received"

    request_id: typing.Union[int, str] = ""
    """Request ID."""

    user: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))
    """The user who sent the request."""

    message: typing.Optional[str] = None
    """Verification message."""


class FriendAddedEvent(EBAEvent):
    """Friend successfully added."""

    type: str = "friend.added"

    user: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))


class FriendRemovedEvent(EBAEvent):
    """Friend was removed."""

    type: str = "friend.removed"

    user: platform_entities.User = pydantic.Field(default_factory=lambda: platform_entities.User(id=""))


# ---- Bot Status Events ----

class BotInvitedToGroupEvent(EBAEvent):
    """Bot was invited to join a group."""

    type: str = "bot.invited_to_group"

    group: platform_entities.UserGroup = pydantic.Field(default_factory=lambda: platform_entities.UserGroup(id=""))
    inviter: typing.Optional[platform_entities.User] = None

    request_id: typing.Optional[typing.Union[int, str]] = None
    """Invitation request ID."""


class BotRemovedFromGroupEvent(EBAEvent):
    """Bot was removed from a group."""

    type: str = "bot.removed_from_group"

    group: platform_entities.UserGroup = pydantic.Field(default_factory=lambda: platform_entities.UserGroup(id=""))
    operator: typing.Optional[platform_entities.User] = None


class BotMutedEvent(EBAEvent):
    """Bot was muted in a group."""

    type: str = "bot.muted"

    group: platform_entities.UserGroup = pydantic.Field(default_factory=lambda: platform_entities.UserGroup(id=""))
    operator: typing.Optional[platform_entities.User] = None
    duration: typing.Optional[int] = None


class BotUnmutedEvent(EBAEvent):
    """Bot was unmuted in a group."""

    type: str = "bot.unmuted"

    group: platform_entities.UserGroup = pydantic.Field(default_factory=lambda: platform_entities.UserGroup(id=""))
    operator: typing.Optional[platform_entities.User] = None


# ---- Platform-Specific Events ----

class PlatformSpecificEvent(EBAEvent):
    """Platform-specific event.

    Used when the adapter cannot map an event to a standard type.
    """

    type: str = "platform.specific"

    action: str = ""
    """Platform-specific action identifier."""

    data: dict = {}
    """Event data; structure defined by each adapter."""


# ---- Message Send Result ----

class MessageResult(pydantic.BaseModel):
    """Result of a message send operation."""

    message_id: typing.Optional[typing.Union[int, str]] = None
    """Message ID after successful send."""

    raw: typing.Optional[dict] = None
    """Raw platform response data."""
