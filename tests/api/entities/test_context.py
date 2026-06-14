from __future__ import annotations

from langbot_plugin.api.entities import context as context_module
from langbot_plugin.api.definition.abstract.platform.adapter import (
    AbstractMessagePlatformAdapter,
)
from langbot_plugin.api.definition.abstract.platform.event_logger import AbstractEventLogger
from langbot_plugin.api.entities.builtin.pipeline.query import Query
from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain
from langbot_plugin.api.entities.builtin.platform.events import FriendMessage
from langbot_plugin.api.entities.builtin.platform.entities import Friend
from langbot_plugin.api.entities.builtin.provider.session import LauncherTypes
from langbot_plugin.api.entities.events import PersonMessageReceived
from langbot_plugin.api.entities.context import EventContext


class MockLogger(AbstractEventLogger):
    async def info(self, text, images=None, message_session_id=None, no_throw=True):
        pass

    async def debug(self, text, images=None, message_session_id=None, no_throw=True):
        pass

    async def warning(self, text, images=None, message_session_id=None, no_throw=True):
        pass

    async def error(self, text, images=None, message_session_id=None, no_throw=True):
        pass


class MockAdapter(AbstractMessagePlatformAdapter):
    config: dict = {}
    logger: MockLogger

    async def send_message(self, target_type, target_id, message):
        pass

    async def reply_message(self, message_source, message, quote_origin=False):
        pass

    async def is_muted(self, group_id):
        return False

    def register_listener(self, event_type, callback):
        pass

    def unregister_listener(self, event_type, callback):
        pass

    async def run_async(self):
        pass

    async def kill(self) -> bool:
        return True


def _make_friend_message(chain: MessageChain) -> FriendMessage:
    return FriendMessage(
        sender=Friend(id="sender", nickname="Tester", remark=""),
        message_chain=chain,
    )


def _make_query(chain: MessageChain) -> Query:
    return Query(
        query_id=1,
        launcher_type=LauncherTypes.PERSON,
        launcher_id="launcher",
        sender_id="sender",
        message_event=_make_friend_message(chain),
        message_chain=chain,
        adapter=MockAdapter(bot_account_id="bot", config={}, logger=MockLogger()),
        session=None,
    )


def _event():
    chain = MessageChain([Plain(text="hello")])
    return PersonMessageReceived(
        query=_make_query(chain),
        launcher_type="person",
        launcher_id="launcher",
        sender_id="sender",
        message_chain=chain,
        message_event=_make_friend_message(chain),
    )


def test_event_context_from_event_assigns_monotonic_id_and_caches_context():
    context_module.cached_event_contexts.clear()
    context_module.global_eid_index = 0

    first = EventContext.from_event(_event())
    second = EventContext.from_event(_event())

    assert first.eid == 0
    assert second.eid == 1
    assert context_module.cached_event_contexts[0] is first
    assert context_module.cached_event_contexts[1] is second
    assert first.event_name == "PersonMessageReceived"


def test_event_context_prevent_flags_are_mutable_runtime_state():
    ctx = EventContext.from_event(_event())

    assert ctx.is_prevented_default() is False
    assert ctx.is_prevented_postorder() is False

    ctx.prevent_default()
    ctx.prevent_postorder()

    assert ctx.is_prevented_default() is True
    assert ctx.is_prevented_postorder() is True


def test_event_context_validates_event_from_serialized_payload():
    event = _event()
    payload = event.model_dump()
    payload["event_name"] = "PersonMessageReceived"

    ctx = EventContext(
        query_id=event.query.query_id,
        eid=99,
        event_name="PersonMessageReceived",
        event=payload,
    )

    assert isinstance(ctx.event, PersonMessageReceived)
    assert ctx.event.sender_id == "sender"


def test_query_variable_helpers_initialize_and_return_runtime_state():
    query = _make_query(MessageChain([Plain(text="hello")]))
    query.variables = None

    assert query.get_variable("missing") is None
    assert query.get_variables() == {}

    query.set_variable("answer", 42)

    assert query.get_variable("answer") == 42
    assert query.get_variables() == {"answer": 42}


def test_query_model_dump_serializes_public_request_payload():
    query = _make_query(MessageChain([Plain(text="hello")]))
    query.bot_uuid = "bot-uuid"
    query.pipeline_uuid = "pipeline-uuid"
    query.pipeline_config = {"enabled": True}

    payload = query.model_dump()

    assert payload["query_id"] == 1
    assert payload["launcher_type"] == "person"
    assert payload["launcher_id"] == "launcher"
    assert payload["sender_id"] == "sender"
    assert payload["bot_uuid"] == "bot-uuid"
    assert payload["pipeline_uuid"] == "pipeline-uuid"
    assert payload["pipeline_config"] == {"enabled": True}
    assert payload["session"] is None
    assert payload["messages"] == []
    assert payload["prompt"] is None
    assert payload["message_chain"][0]["text"] == "hello"
