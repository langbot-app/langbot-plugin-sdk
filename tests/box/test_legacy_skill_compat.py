"""Coverage for the temporary old-Core rolling-upgrade bridge."""

from __future__ import annotations

import pytest

from langbot_plugin.box.actions import LangBotToBoxAction
from langbot_plugin.box.client import BoxRuntimeClient
from langbot_plugin.box.legacy_skill_compat import LegacySkillCompat
from langbot_plugin.box.models import BoxSpec
from langbot_plugin.entities.io.context import ActionContext


_CONTEXT = ActionContext(
    instance_uuid="instance-a",
    workspace_uuid="workspace-a",
    placement_generation=1,
)


def test_normal_box_protocol_has_no_skill_surface():
    assert all("skill" not in action.value for action in LangBotToBoxAction)
    assert "skill_name" not in BoxSpec.model_fields
    assert not hasattr(BoxRuntimeClient, "list_skills")


@pytest.mark.anyio
async def test_legacy_skill_name_is_translated_outside_box_model(tmp_path):
    config = {
        "local": {
            "host_root": str(tmp_path),
            "skills_root": "skills",
        }
    }
    compat = LegacySkillCompat(lambda: config)
    created = await compat.call(
        _CONTEXT,
        "create_skill",
        {"name": "demo", "instructions": "Run the demo."},
    )

    payload = await compat.normalize_spec_payload(
        {"session_id": "global", "cmd": "true", "skill_name": "demo"},
        _CONTEXT,
    )
    spec = BoxSpec.model_validate(payload)

    assert "skill_name" not in payload
    assert spec.extra_mounts[0].host_path == created["package_root"]
    assert spec.extra_mounts[0].mount_path == "/workspace/.skills/demo"
    assert spec.extra_mounts[0].mode.value == "ro"
