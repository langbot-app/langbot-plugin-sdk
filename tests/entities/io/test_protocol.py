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
from langbot_plugin.entities.io.context import (
    ActionContext,
    ApplyPluginInstallationRequest,
    InstallationBinding,
    PluginInstallationDesiredState,
    PluginWorkerPolicy,
    ReconcilePluginInstallationsRequest,
    RuntimeConfig,
    RuntimeIdentity,
)


ARTIFACT_DIGEST = "a" * 64


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


def test_action_request_serializes_optional_workspace_context_envelope():
    context = ActionContext(
        instance_uuid="instance-1",
        workspace_uuid="workspace-a",
        placement_generation=7,
        installation_uuid="installation-1",
    )

    request = ActionRequest.make_request(7, "ping", {}, context)

    assert request.model_dump() == {
        "seq_id": 7,
        "action": "ping",
        "data": {},
        "context": context.model_dump(),
    }
    assert ActionRequest.model_validate(request.model_dump()).context == context


def test_action_request_preserves_complete_installation_binding():
    binding = InstallationBinding(
        instance_uuid="instance-1",
        workspace_uuid="workspace-a",
        placement_generation=7,
        installation_uuid="installation-1",
        runtime_revision=3,
        artifact_digest=ARTIFACT_DIGEST,
    )

    request = ActionRequest.make_request(8, "list_plugins", {}, binding)
    round_tripped = ActionRequest.model_validate(request.model_dump())

    assert request.model_dump()["context"] == binding.model_dump()
    assert isinstance(round_tripped.context, InstallationBinding)
    assert round_tripped.context == binding
    assert binding.execution_generation == 7


def test_runtime_config_models_are_frozen_and_instance_scoped():
    identity = RuntimeIdentity(instance_uuid="instance-1", runtime_id="runtime-boot-1")
    policy = PluginWorkerPolicy(
        max_cpus=1.0,
        max_memory_mb=512,
        max_pids=128,
        max_open_files=256,
        max_file_size_mb=512,
    )
    config = RuntimeConfig(
        runtime_identity=identity,
        worker_policy=policy,
        cloud_service_url="https://space.example/",
    )

    assert config.cloud_service_url == "https://space.example"
    assert config.runtime_profile == "oss_dev"
    assert policy.require_hard_limits is False
    assert policy.effective_worker_capacity == 8
    with pytest.raises(ValidationError):
        identity.runtime_id = "runtime-boot-2"
    with pytest.raises(ValidationError):
        policy.max_pids = 256
    with pytest.raises(ValidationError):
        RuntimeConfig.model_validate(
            {
                **config.model_dump(),
                "workspace_uuid": "workspace-a",
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "installation_uuid": "",
            "runtime_revision": 1,
            "artifact_digest": ARTIFACT_DIGEST,
        },
        {
            "installation_uuid": "installation-1",
            "runtime_revision": "1",
            "artifact_digest": ARTIFACT_DIGEST,
        },
        {
            "installation_uuid": "installation-1",
            "runtime_revision": 0,
            "artifact_digest": ARTIFACT_DIGEST,
        },
        {
            "installation_uuid": "installation-1",
            "runtime_revision": 1,
            "artifact_digest": "not-a-sha256",
        },
    ],
)
def test_installation_binding_rejects_incomplete_worker_tuple(payload):
    with pytest.raises(ValidationError):
        InstallationBinding.model_validate(
            {
                "instance_uuid": "instance-1",
                "workspace_uuid": "workspace-a",
                "placement_generation": 1,
                **payload,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_cpus", 0),
        ("max_cpus", "1.0"),
        ("max_cpus", float("nan")),
        ("max_cpus", float("inf")),
        ("max_memory_mb", 0),
        ("max_memory_mb", "512"),
        ("max_pids", -1),
        ("max_open_files", False),
        ("max_file_size_mb", 0),
    ],
)
def test_plugin_worker_policy_rejects_non_positive_limits(field, value):
    payload = {
        "max_cpus": 1.0,
        "max_memory_mb": 512,
        "max_pids": 128,
        "max_open_files": 256,
        "max_file_size_mb": 512,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        PluginWorkerPolicy.model_validate(payload)


def test_desired_state_protocol_requires_unique_complete_bindings():
    binding = InstallationBinding(
        instance_uuid="instance-1",
        workspace_uuid="workspace-a",
        placement_generation=1,
        installation_uuid="installation-1",
        runtime_revision=1,
        artifact_digest=ARTIFACT_DIGEST,
    )
    desired = PluginInstallationDesiredState(binding=binding, enabled=True)

    request = ReconcilePluginInstallationsRequest(installations=(desired,))

    assert request.installations == (desired,)
    assert ApplyPluginInstallationRequest(artifact_file_key=None).enabled is True
    with pytest.raises(ValidationError, match="unique installation_uuid"):
        ReconcilePluginInstallationsRequest(installations=(desired, desired))


@pytest.mark.parametrize(
    "payload",
    [
        {
            "instance_uuid": "",
            "workspace_uuid": "workspace-a",
            "placement_generation": 1,
        },
        {
            "instance_uuid": "instance-1",
            "workspace_uuid": "",
            "placement_generation": 1,
        },
        {
            "instance_uuid": "instance-1",
            "workspace_uuid": "workspace-a",
            "placement_generation": 0,
        },
    ],
)
def test_action_context_rejects_incomplete_or_unfenced_binding(payload):
    with pytest.raises(ValidationError):
        ActionContext.model_validate(payload)


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
    response = ActionResponse(
        seq_id=1, code=0, message="ok", data={}, chunk_status=None
    )
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
