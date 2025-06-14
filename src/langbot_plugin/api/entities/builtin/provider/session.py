import typing
import datetime
import asyncio

import pydantic

import langbot_plugin.api.entities.builtin.provider.prompt as provider_prompt
import langbot_plugin.api.entities.builtin.provider.message as provider_message
import langbot_plugin.api.entities.builtin.pipeline as pipeline_entities


class Conversation(pydantic.BaseModel):
    """对话，包含于 Session 中，一个 Session 可以有多个历史 Conversation，但只有一个当前使用的 Conversation"""

    prompt: provider_prompt.Prompt

    messages: list[provider_message.Message]

    create_time: typing.Optional[datetime.datetime] = pydantic.Field(
        default_factory=datetime.datetime.now
    )

    update_time: typing.Optional[datetime.datetime] = pydantic.Field(
        default_factory=datetime.datetime.now
    )

    uuid: typing.Optional[str] = None
    """The uuid of the conversation, not automatically generated when created.
    Instead, when using Dify API or other services that manage conversation information externally,
    it is used to bind the external session. The specific usage depends on the Runner."""

    class Config:
        arbitrary_types_allowed = True


class Session(pydantic.BaseModel):
    """Session, one Session corresponds to a {launcher_type.value}_{launcher_id}"""

    launcher_type: pipeline_entities.LauncherTypes

    launcher_id: typing.Union[int, str]

    sender_id: typing.Optional[typing.Union[int, str]] = 0

    use_prompt_name: typing.Optional[str] = "default"

    using_conversation: typing.Optional[Conversation] = None

    conversations: typing.Optional[list[Conversation]] = pydantic.Field(
        default_factory=list
    )

    create_time: typing.Optional[datetime.datetime] = pydantic.Field(
        default_factory=datetime.datetime.now
    )

    update_time: typing.Optional[datetime.datetime] = pydantic.Field(
        default_factory=datetime.datetime.now
    )

    semaphore: typing.Optional[asyncio.Semaphore] = None
    """The semaphore of the current session, used to limit concurrency"""

    class Config:
        arbitrary_types_allowed = True
