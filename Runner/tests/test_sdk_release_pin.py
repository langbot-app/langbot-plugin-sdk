"""Assert exact released SDK pins without conflating independent release lanes."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SDK_REQUIREMENT = "langbot-plugin==0.6.0b5"
CODING_PLUGINS = {"acp-agent-runner", "claude-code-agent", "codex-agent"}
HTTP_PLUGINS = {
    "coze-agent",
    "dashscope-agent",
    "deerflow-agent",
    "dify-agent",
    "langflow-agent",
    "n8n-agent",
    "tbox-agent",
    "weknora-agent",
}
EXPECTED_SDK = {
    **dict.fromkeys(CODING_PLUGINS, "langbot-plugin==0.6.0b3"),
    **dict.fromkeys(HTTP_PLUGINS | {"LocalAgent", "RunnerDemo"}, SDK_REQUIREMENT),
}
PLUGINS = sorted(p.parent for p in ROOT.glob("*/manifest.yaml"))


def test_sdk_policy_covers_exact_plugin_inventory():
    assert {p.name for p in PLUGINS} == set(EXPECTED_SDK)


@pytest.mark.parametrize("plugin", PLUGINS, ids=lambda p: p.name)
def test_plugin_requirements_pin_released_sdk(plugin):
    requirements = (plugin / "requirements.txt").read_text().splitlines()
    assert EXPECTED_SDK[plugin.name] in requirements
    assert sum(line.startswith("langbot-plugin") for line in requirements) == 1


@pytest.mark.parametrize("project", [ROOT, ROOT / "LocalAgent"], ids=["runners", "localagent"])
def test_project_uses_released_sdk_without_local_override(project):
    config = tomllib.loads((project / "pyproject.toml").read_text())
    assert SDK_REQUIREMENT in config["project"]["dependencies"]
    assert "langbot-plugin" not in config.get("tool", {}).get("uv", {}).get("sources", {})
