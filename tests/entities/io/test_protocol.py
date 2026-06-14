from __future__ import annotations

import pytest
from pydantic import ValidationError

from langbot_plugin.entities.io.actions.enums import (
    CommonAction,
    LangBotToRuntimeAction,
    PluginToRuntimeAction,
    RuntimeToLangBotAction,
    RuntimeToPluginAction,
)
from langbot_plugin.entities.io.errors import (
    ActionCallError,
    ActionCallTimeoutError,
    ConnectionClosedError,
)
from langbot_plugin.entities.io.req import ActionRequest
from langbot_plugin.entities.io.resp import ActionResponse, ChunkStatus


def test_action_request_factory_preserves_protocol_fields():
    request = ActionRequest.make_request(
        seq_id=42,
        action=PluginToRuntimeAction.GET_BOT_UUID.value,
        data={"query_id": 1001},
    )

    assert request.seq_id == 42
    assert request.action == "get_bot_uuid"
    assert request.data == {"query_id": 1001}
    assert request.model_dump() == {
        "seq_id": 42,
        "action": "get_bot_uuid",
        "data": {"query_id": 1001},
    }


def test_action_request_requires_mapping_data():
    with pytest.raises(ValidationError):
        ActionRequest(seq_id=1, action="ping", data=["not", "a", "dict"])


def test_action_response_success_error_and_chunk_serialization():
    success = ActionResponse.success({"ok": True})
    assert success.seq_id == 0
    assert success.code == 0
    assert success.message == "success"
    assert success.model_dump()["chunk_status"] == "continue"

    error = ActionResponse.error("boom")
    assert error.seq_id is None
    assert error.code == 1
    assert error.data == {}

    end = ActionResponse(
        seq_id=99,
        code=0,
        message="done",
        data={},
        chunk_status=ChunkStatus.END,
    )
    dumped = end.model_dump()
    assert dumped["chunk_status"] == "end"
    assert ActionResponse.model_validate(dumped).chunk_status is ChunkStatus.END


def test_action_response_normalizes_missing_chunk_status_to_continue():
    response = ActionResponse(seq_id=1, code=0, message="ok", data={}, chunk_status=None)
    assert response.chunk_status is ChunkStatus.CONTINUE


def test_protocol_error_messages_are_stable_strings():
    assert str(ConnectionClosedError("closed")) == "closed"
    assert str(ActionCallTimeoutError("slow")) == "slow"
    assert str(ActionCallError("failed")) == "failed"


def test_action_values_are_unique_inside_each_protocol_direction():
    for action_group in (
        CommonAction,
        PluginToRuntimeAction,
        RuntimeToPluginAction,
        LangBotToRuntimeAction,
        RuntimeToLangBotAction,
    ):
        values = [action.value for action in action_group]
        assert len(values) == len(set(values)), action_group.__name__
