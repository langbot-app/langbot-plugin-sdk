from __future__ import annotations

import base64

import pytest

from langbot_plugin.api.entities.builtin.platform.message import (
    File,
    Image,
    MessageChain,
    Plain,
)
from langbot_plugin.api.entities.builtin.provider.message import (
    ContentElement,
    Message,
    MessageChunk,
)
from langbot_plugin.api.entities.builtin.runner.result import (
    MessageCompletedPayload,
    MessageDeltaPayload,
    RunCompletedPayload,
    RunnerResult,
)


@pytest.mark.parametrize("message_type", [Message, MessageChunk])
@pytest.mark.parametrize("data", [b"hello\n", b"\x00\xff\x80\x01", b""])
def test_base64_file_preserves_bytes_and_unicode_name(message_type, data):
    encoded = base64.b64encode(data).decode("ascii")
    message = message_type(
        role="assistant",
        content=[ContentElement.from_file_base64(encoded, "报告.bin")],
    )

    chain = message.get_content_platform_message_chain()

    assert len(chain) == 1
    assert isinstance(chain[0], File)
    assert chain[0].base64 == encoded
    assert base64.b64decode(chain[0].base64) == data
    assert chain[0].name == "报告.bin"
    assert chain[0].url == ""


@pytest.mark.parametrize("message_type", [Message, MessageChunk])
@pytest.mark.parametrize("name", [None, "", "report.txt"])
def test_base64_file_supports_optional_file_name(message_type, name):
    message = message_type(
        role="assistant",
        content=[
            ContentElement(type="file_base64", file_base64="aGVsbG8=", file_name=name)
        ],
    )

    chain = message.get_content_platform_message_chain()

    assert len(chain) == 1
    assert isinstance(chain[0], File)
    assert chain[0].name == (name or "")
    assert chain[0].base64 == "aGVsbG8="


@pytest.mark.parametrize("message_type", [Message, MessageChunk])
def test_base64_files_preserve_mixed_content_order_and_first_text_prefix(message_type):
    message = message_type(
        role="assistant",
        content=[
            ContentElement.from_file_base64("Zmlyc3Q=", "first.txt"),
            ContentElement.from_image_base64("aW1hZ2U="),
            ContentElement.from_text("first text"),
            ContentElement.from_file_url(
                "https://example.com/report.txt", "remote.txt"
            ),
            ContentElement.from_file_base64("c2Vjb25k", "second.txt"),
            ContentElement.from_text("second text"),
        ],
    )
    original = message.model_dump(mode="json")

    chain = message.get_content_platform_message_chain(prefix_text="[bot] ")

    assert [type(component) for component in chain] == [
        File,
        Image,
        Plain,
        File,
        File,
        Plain,
    ]
    assert [chain[index].name for index in (0, 3, 4)] == [
        "first.txt",
        "remote.txt",
        "second.txt",
    ]
    assert chain[0].base64 == "Zmlyc3Q="
    assert chain[3].url == "https://example.com/report.txt"
    assert chain[4].base64 == "c2Vjb25k"
    assert chain[2].text == "[bot] first text"
    assert chain[5].text == "second text"
    assert message.model_dump(mode="json") == original


@pytest.mark.parametrize("message_type", [Message, MessageChunk])
def test_file_only_content_inserts_prefix_before_file(message_type):
    message = message_type(
        role="assistant",
        content=[ContentElement.from_file_base64("ZmlsZQ==", "report.txt")],
    )

    chain = message.get_content_platform_message_chain(prefix_text="[bot] ")

    assert [type(component) for component in chain] == [Plain, File]
    assert chain[0].text == "[bot] "
    assert chain[1].base64 == "ZmlsZQ=="


@pytest.mark.parametrize("message_type", [Message, MessageChunk])
def test_base64_file_without_payload_is_skipped(message_type):
    message = message_type(
        role="assistant",
        content=[ContentElement(type="file_base64", file_name="missing.txt")],
    )

    chain = message.get_content_platform_message_chain()

    assert len(chain) == 0


@pytest.mark.parametrize("message_type", [Message, MessageChunk])
def test_host_attachments_follow_content_files_without_mutating_input(message_type):
    attachments = MessageChain([File(name="host.txt", base64="aG9zdA==")])
    message = message_type(
        role="assistant",
        content=[ContentElement.from_file_base64("Y29udGVudA==", "content.txt")],
        attachments=attachments,
    )
    original_content = message.model_dump(mode="json")
    original_attachments = attachments.model_dump()

    for _ in range(2):
        chain = message.get_content_platform_message_chain(prefix_text="[bot] ")
        assert [type(component) for component in chain] == [Plain, File, File]
        assert [chain[1].name, chain[2].name] == ["content.txt", "host.txt"]
        assert [chain[1].base64, chain[2].base64] == ["Y29udGVudA==", "aG9zdA=="]

    assert message.model_dump(mode="json") == original_content
    assert message.attachments.model_dump() == original_attachments


@pytest.mark.parametrize(
    "message_type,result_factory,payload_type,payload_attribute",
    [
        (MessageChunk, RunnerResult.message_delta, MessageDeltaPayload, "chunk"),
        (Message, RunnerResult.message_completed, MessageCompletedPayload, "message"),
        (Message, RunnerResult.run_completed, RunCompletedPayload, "message"),
    ],
)
def test_base64_file_survives_runner_result_json_roundtrip(
    message_type, result_factory, payload_type, payload_attribute
):
    data = b"\x00\xff\x80runner-file\n"
    encoded = base64.b64encode(data).decode("ascii")
    message = message_type(
        role="assistant",
        content=[ContentElement.from_file_base64(encoded, "report.bin")],
    )
    result = result_factory("run-1", message, sequence=3)

    restored_result = RunnerResult.model_validate_json(result.model_dump_json())
    restored_payload = payload_type.model_validate(restored_result.data)
    restored_message = getattr(restored_payload, payload_attribute)
    chain = restored_message.get_content_platform_message_chain()

    assert restored_result.sequence == 3
    assert len(chain) == 1
    assert isinstance(chain[0], File)
    assert chain[0].name == "report.bin"
    assert base64.b64decode(chain[0].base64) == data
