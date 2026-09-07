"""Explicit EBA handlers, concurrent invocation and legacy event preservation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from langbot_plugin.api.definition.components.event_processor import EventProcessor
from langbot_plugin.api.entities.builtin.platform import events, entities, message


def context(run_id="one", event_type="group.member_joined"):
    return SimpleNamespace(
        run_id=run_id,
        config={"prefix": run_id},
        event=SimpleNamespace(data={"type": event_type, "member": {"id": run_id}}),
    )


def processor():
    component = EventProcessor()
    component.get_run_api = Mock(
        return_value=SimpleNamespace(call_tool=AsyncMock(return_value={"ok": True}))
    )
    return component


async def test_one_event_invokes_once_and_completes_without_model_loop():
    component = processor()
    calls = []

    @component.handler(events.MemberJoinedEvent)
    async def handle(ctx):
        calls.append(ctx.event.member.id)
        await ctx.log("received")
        await ctx.reply("Welcome")

    results = [result async for result in component.run(context())]
    assert calls == ["one"]
    assert [result.type for result in results] == [
        "processor.log",
        "tool.call.started",
        "tool.call.completed",
        "run.completed",
    ]
    component.get_run_api.return_value.call_tool.assert_awaited_once_with(
        "event_reply", {"text": "Welcome"}
    )


async def test_concurrent_instances_keep_invocation_context_and_logs_separate():
    component = processor()

    @component.handler(events.EBAEvent)
    async def handle(ctx):
        await asyncio.sleep(0)
        await ctx.log(ctx.config["prefix"] + ctx.event.member.id)

    async def collect(run_id):
        return [result async for result in component.run(context(run_id))]

    first, second = await asyncio.gather(collect("first"), collect("second"))
    assert first[0].data["text"] == "firstfirst"
    assert second[0].data["text"] == "secondsecond"
    assert all(item.run_id == "first" for item in first)
    assert processor().registered_handlers == {}


async def test_failure_preserves_prior_logs_and_does_not_report_completion():
    component = processor()

    @component.handler(events.EBAEvent)
    async def handle(ctx):
        await ctx.log("before error")
        raise RuntimeError("handler failed")

    results = []
    with pytest.raises(RuntimeError, match="handler failed"):
        async for result in component.run(context()):
            results.append(result)
    assert [item.type for item in results] == ["processor.log"]


async def test_closing_stream_cancels_handler():
    component = processor()
    stopped = asyncio.Event()

    @component.handler(events.EBAEvent)
    async def handle(ctx):
        try:
            await ctx.log("started")
            await asyncio.Event().wait()
        finally:
            stopped.set()

    stream = component.run(context())
    assert (await anext(stream)).type == "processor.log"
    await stream.aclose()
    assert stopped.is_set()


async def test_missing_handler_fails_explicitly():
    with pytest.raises(ValueError, match="No handler"):
        await anext(processor().run(context()))


@pytest.mark.parametrize("event_class", events.EBAEvent.__subclasses__())
def test_all_builtin_eba_types_deserialize(event_class):
    event = events.parse_eba_event(
        {
            "type": event_class.model_fields["type"].default,
            "feedback_id": "test",
            "feedback_type": 1,
        }
    )
    assert type(event) is event_class


def test_remote_event_cannot_supply_host_only_original():
    event = events.parse_eba_event(
        {
            "type": "message.received",
            "source_platform_object": {"secret": True},
            "legacy_event": {"invalid": "host-only"},
        }
    )
    assert event.legacy_event is None
    assert event.source_platform_object is None


def test_legacy_roundtrip_preserves_permissions_title_and_message_edits():
    group = entities.Group(
        id=1, name="Group", permission=entities.Permission.Administrator
    )
    legacy = events.GroupMessage(
        sender=entities.GroupMember(
            id=2,
            member_name="Card",
            permission=entities.Permission.Owner,
            special_title="Title",
            group=group,
        ),
        message_chain=message.MessageChain([message.Plain(text="Original")]),
        source_platform_object=object(),
    )
    eba = events.MessageReceivedEvent(
        legacy_event=legacy,
        message_chain=message.MessageChain([message.Plain(text="Edited")]),
        source_platform_object=legacy.source_platform_object,
    )
    restored = eba.to_legacy_event()
    assert restored.sender == legacy.sender
    assert restored.source_platform_object is legacy.source_platform_object
    assert str(restored.message_chain) == "Edited"
    assert "legacy_event" not in eba.model_dump()


def test_eba_membership_projects_legacy_fields():
    user = entities.User(id=2, nickname="Nick")
    event = events.MessageReceivedEvent(
        sender=user,
        chat_type="group",
        chat_id=1,
        sender_member=entities.UserGroupMember(
            user=user, group_id=1, role="owner", display_name="Card", title="Title"
        ),
        bot_role="admin",
    )
    restored = event.to_legacy_event()
    assert restored.sender.member_name == "Card"
    assert restored.sender.special_title == "Title"
    assert restored.sender.permission == entities.Permission.Owner
    assert restored.sender.group.permission == entities.Permission.Administrator


async def test_tool_failure_is_logged_before_run_failure():
    component = processor()
    component.get_run_api.return_value.call_tool.side_effect = ValueError(
        "delivery failed"
    )

    @component.handler(events.EBAEvent)
    async def handle(ctx):
        await ctx.api.call_tool("event_reply", {"text": "Hi"})

    results = []
    with pytest.raises(ValueError, match="delivery failed"):
        async for result in component.run(context()):
            results.append(result)
    assert [item.type for item in results] == [
        "tool.call.started",
        "tool.call.completed",
    ]
    assert results[-1].data["error"] == "delivery failed"
