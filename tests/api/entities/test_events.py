import pytest
from langbot_plugin.api.entities.events import (
    BaseEventModel,
    PersonMessageReceived,
    GroupMessageReceived,
    PersonNormalMessageReceived,
    PersonCommandSent,
    GroupNormalMessageReceived,
    GroupCommandSent,
    NormalMessageResponded,
    PromptPreProcessing,
)
from langbot_plugin.api.entities.builtin.platform.message import (
    MessageChain,
    Plain,
    Image,
)
from langbot_plugin.api.entities.builtin.provider.session import Session, LauncherTypes
from langbot_plugin.api.entities.builtin.provider.message import Message
from langbot_plugin.api.entities.builtin.pipeline.query import Query
from langbot_plugin.api.entities.builtin.platform.events import MessageEvent, FriendMessage, GroupMessage
from langbot_plugin.api.entities.builtin.platform.entities import (
    Friend,
    Group,
    GroupMember,
    Permission,
)
from langbot_plugin.api.definition.abstract.platform.adapter import (
    AbstractMessagePlatformAdapter,
)
from langbot_plugin.api.definition.abstract.platform.event_logger import (
    AbstractEventLogger,
)
from typing import Optional, List


class MockLogger(AbstractEventLogger):
    async def info(
        self,
        text: str,
        images: Optional[List[Image]] = None,
        message_session_id: Optional[str] = None,
        no_throw: bool = True,
    ):
        pass

    async def debug(
        self,
        text: str,
        images: Optional[List[Image]] = None,
        message_session_id: Optional[str] = None,
        no_throw: bool = True,
    ):
        pass

    async def warning(
        self,
        text: str,
        images: Optional[List[Image]] = None,
        message_session_id: Optional[str] = None,
        no_throw: bool = True,
    ):
        pass

    async def error(
        self,
        text: str,
        images: Optional[List[Image]] = None,
        message_session_id: Optional[str] = None,
        no_throw: bool = True,
    ):
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


def _make_friend_message(mc=None):
    if mc is None:
        mc = MessageChain([Plain(text="hi")])
    return FriendMessage(
        sender=Friend(id="789012", nickname="Test", remark=""),
        message_chain=mc,
    )


def _make_group_message(mc=None):
    if mc is None:
        mc = MessageChain([Plain(text="hi")])
    return GroupMessage(
        sender=GroupMember(
            id="789012",
            member_name="Test",
            permission=Permission.Member,
            group=Group(id="123456", name="TestGroup", permission=Permission.Member),
        ),
        message_chain=mc,
    )


def make_mock_query():
    # 构造最小可用 Query 实例
    return Query(
        query_id=1,
        launcher_type=LauncherTypes.PERSON,
        launcher_id="test_launcher",
        sender_id="test_sender",
        message_event=_make_friend_message(),
        message_chain=MessageChain([Plain(text="hi")]),
        adapter=MockAdapter(bot_account_id="bot", config={}, logger=MockLogger()),
        session=None,
    )


def test_base_event_model():
    data = {"query": make_mock_query()}
    model = BaseEventModel(**data)
    assert model.query is not None
    # query is excluded from serialization (exclude=True in field definition)
    # so we verify it's accessible on the model directly
    assert model.query.query_id == 1
    assert model.query.launcher_type == LauncherTypes.PERSON


def test_person_message_received():
    mc = MessageChain([Plain(text="Hello")])
    data = {
        "query": make_mock_query(),
        "launcher_type": "person",
        "launcher_id": "123456",
        "sender_id": "789012",
        "message_chain": mc,
        "message_event": _make_friend_message(mc),
    }
    model = PersonMessageReceived(**data)
    assert isinstance(model.message_chain, MessageChain)
    # 测试序列化
    serialized = model.model_dump()
    # query is excluded from serialization, verify it's not in the output
    assert "query" not in serialized
    assert serialized["launcher_type"] == "person"
    assert isinstance(serialized["message_chain"], list)


def test_group_message_received():
    mc = MessageChain([Plain(text="Hello")])
    data = {
        "query": make_mock_query(),
        "launcher_type": "group",
        "launcher_id": "123456",
        "sender_id": "789012",
        "message_chain": mc,
        "message_event": _make_group_message(mc),
    }
    model = GroupMessageReceived(**data)
    assert isinstance(model.message_chain, MessageChain)
    serialized = model.model_dump()
    assert "query" not in serialized
    assert serialized["launcher_type"] == "group"
    assert isinstance(serialized["message_chain"], list)


def test_person_normal_message_received():
    mc = MessageChain([Plain(text="Hello")])
    data = {
        "query": make_mock_query(),
        "launcher_type": "person",
        "launcher_id": "123456",
        "sender_id": "789012",
        "text_message": "Hello",
        "alter": "Modified Hello",
        "reply": [],
        "message_chain": mc,
        "message_event": _make_friend_message(mc),
    }

    model = PersonNormalMessageReceived(**data)
    assert model.text_message == "Hello"


def test_person_command_sent():
    data = {
        "query": make_mock_query(),
        "launcher_type": "person",
        "launcher_id": "123456",
        "sender_id": "789012",
        "command": "test",
        "params": ["param1", "param2"],
        "text_message": "/test param1 param2",
        "is_admin": True,
        "alter": "/test param1 param2",
        "reply": [],
    }

    model = PersonCommandSent(**data)
    assert model.command == "test"
    assert model.params == ["param1", "param2"]
    assert model.is_admin is True


def test_group_normal_message_received():
    mc = MessageChain([Plain(text="Hello Group")])
    data = {
        "query": make_mock_query(),
        "launcher_type": "group",
        "launcher_id": "123456",
        "sender_id": "789012",
        "text_message": "Hello Group",
        "alter": "Modified Hello Group",
        "reply": [],
        "message_chain": mc,
        "message_event": _make_group_message(mc),
    }

    model = GroupNormalMessageReceived(**data)
    assert model.text_message == "Hello Group"


def test_group_command_sent():
    data = {
        "query": make_mock_query(),
        "launcher_type": "group",
        "launcher_id": "123456",
        "sender_id": "789012",
        "command": "test",
        "params": ["param1", "param2"],
        "text_message": "/test param1 param2",
        "is_admin": True,
        "alter": "/test param1 param2",
        "reply": [],
    }

    model = GroupCommandSent(**data)
    assert model.command == "test"
    assert model.params == ["param1", "param2"]
    assert model.is_admin is True


def test_normal_message_responded():
    data = {
        "query": make_mock_query(),
        "launcher_type": "group",
        "launcher_id": "123456",
        "sender_id": "789012",
        "session": Session(
            launcher_type=LauncherTypes.GROUP, launcher_id="123456"
        ).model_dump(),
        "prefix": "Bot: ",
        "response_text": "Hello",
        "finish_reason": "stop",
        "funcs_called": ["func1", "func2"],
        "reply": [],
    }

    model = NormalMessageResponded(**data)
    assert model.prefix == "Bot: "
    assert model.response_text == "Hello"
    assert model.finish_reason == "stop"
    assert model.funcs_called == ["func1", "func2"]
    assert isinstance(model.session, Session)


def test_prompt_pre_processing():
    data = {
        "query": make_mock_query(),
        "session_name": "test_session",
        "default_prompt": [Message(role="user", content="default").model_dump()],
        "prompt": [Message(role="user", content="test").model_dump()],
    }

    model = PromptPreProcessing(**data)
    assert model.session_name == "test_session"
    assert len(model.default_prompt) == 1
    assert len(model.prompt) == 1
    assert isinstance(model.default_prompt[0], Message)
    assert isinstance(model.prompt[0], Message)


def test_validation_errors():
    # 测试缺少必需字段
    with pytest.raises(Exception):
        PersonMessageReceived(query=None)

    # 测试类型错误
    with pytest.raises(Exception):
        PersonMessageReceived(
            query=make_mock_query(),
            launcher_type=123,  # 应该是字符串
            launcher_id="123456",
            sender_id="789012",
            message_chain=MessageChain([Plain(text="Hello")]).model_dump(),
        )
