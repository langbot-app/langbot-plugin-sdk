"""Tests for AgentRunner structured interaction Protocol v1 entities."""

from __future__ import annotations

from pathlib import Path

import pydantic
import pytest
import yaml

from langbot_plugin.api.entities.builtin.agent_runner import (
    INTERACTION_REQUESTED_ACTION,
    INTERACTION_SUBMITTED_EVENT,
    AgentInput,
    AgentRunResult,
    AgentRunnerCapabilities,
    AgentRunnerPermissions,
    DeliveryContext,
    InteractionAction,
    InteractionDeliveryCapabilities,
    InteractionField,
    InteractionOption,
    InteractionRequest,
    InteractionSubmission,
)


def _request() -> InteractionRequest:
    return InteractionRequest(
        interaction_id="approval-1",
        kind="form",
        title="Approve deployment?",
        fields=[
            InteractionField(
                id="priority",
                label="Priority",
                type="select",
                required=True,
                options=[
                    InteractionOption(value="normal", label="Normal"),
                    InteractionOption(value="urgent", label="Urgent"),
                ],
                default="normal",
            )
        ],
        actions=[InteractionAction(id="approve", label="Approve", style="primary")],
        fallback_text="Reply with a priority and approval action.",
    )


def test_interaction_request_is_strict_and_json_serializable() -> None:
    request = _request()

    dumped = request.model_dump(mode="json")
    assert dumped["fields"][0]["options"][1]["value"] == "urgent"
    assert dumped["actions"][0]["style"] == "primary"

    with pytest.raises(pydantic.ValidationError):
        InteractionRequest.model_validate(
            {
                **dumped,
                "provider_form_token": "must-not-cross-the-host-boundary",
            }
        )


def test_submission_accepts_nested_json_values() -> None:
    submission = InteractionSubmission(
        interaction_id="approval-1",
        action_id="approve",
        values={
            "metadata": {
                "attempt": 2,
                "flags": [True, None, "reviewed"],
            }
        },
        submitted_at=1_700_000_000,
    )

    assert submission.values["metadata"] == {
        "attempt": 2,
        "flags": [True, None, "reviewed"],
    }


def test_input_and_delivery_expose_typed_interactions() -> None:
    submission = InteractionSubmission(interaction_id="approval-1", action_id="approve")
    agent_input = AgentInput(text="approve", interaction=submission)
    delivery = DeliveryContext(
        surface="platform",
        interactions=InteractionDeliveryCapabilities(
            field_types=["select"],
            action_styles=["default", "primary", "danger"],
            max_fields=1,
        ),
    )

    assert agent_input.interaction is submission
    assert delivery.interactions is not None
    assert delivery.interactions.field_types == ["select"]


def test_manifest_declares_interaction_capability_and_permission() -> None:
    capabilities = AgentRunnerCapabilities(interactions=True)
    permissions = AgentRunnerPermissions(interactions=["request"])

    assert capabilities.interactions is True
    assert permissions.interactions == ["request"]
    with pytest.raises(pydantic.ValidationError):
        AgentRunnerPermissions(interactions=["submit"])


def test_interaction_requested_factory_uses_whitelisted_action_without_target() -> None:
    result = AgentRunResult.interaction_requested("run-1", _request(), sequence=3)

    assert result.type.value == "action.requested"
    assert result.data["action"] == INTERACTION_REQUESTED_ACTION
    assert result.data["target"] is None
    assert result.data["payload"]["interaction_id"] == "approval-1"
    assert result.sequence == 3
    assert INTERACTION_SUBMITTED_EVENT == "interaction.submitted"


def test_agent_runner_templates_include_interaction_contract() -> None:
    root = Path(__file__).resolve().parents[5]
    template_dir = root / "src" / "langbot_plugin" / "assets" / "templates" / "components" / "agent_runner"
    manifest_source = (template_dir / "{runner_name}.yaml.example").read_text(encoding="utf-8")
    manifest_source = (
        manifest_source.replace("{{ runner_name }}", "default")
        .replace("{{ runner_label }}", "Default Runner")
        .replace("{{ runner_description }}", "Default runner description")
        .replace("{{ runner_attr }}", "DefaultRunner")
    )
    manifest = yaml.safe_load(manifest_source)
    runner_source = (template_dir / "{runner_name}.py.example").read_text(encoding="utf-8")

    assert manifest["spec"]["capabilities"]["interactions"] is False
    assert manifest["spec"]["permissions"]["interactions"] == []
    assert "AgentRunResult.interaction_requested" in runner_source
    assert "INTERACTION_SUBMITTED_EVENT" in runner_source
    assert "ctx.input.interaction" in runner_source
