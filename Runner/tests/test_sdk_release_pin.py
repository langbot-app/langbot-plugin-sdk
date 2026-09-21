"""Release consumers must test and install the same immutable SDK beta."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SDK_REQUIREMENT = "langbot-plugin==0.6.0b3"
PLUGINS = sorted(p.parent for p in ROOT.glob("*/manifest.yaml"))


@pytest.mark.parametrize("plugin", PLUGINS, ids=lambda p: p.name)
def test_plugin_requirements_pin_released_sdk(plugin):
    requirements = (plugin / "requirements.txt").read_text().splitlines()
    # Certified plugins use the deployed b5 Runtime; older runners retain b3.
    expected = "langbot-plugin==0.6.0b5" if plugin.name in {"RunnerDemo", "LocalAgent"} else SDK_REQUIREMENT
    assert expected in requirements
    assert sum(line.startswith("langbot-plugin") for line in requirements) == 1


@pytest.mark.parametrize("project", [ROOT, ROOT / "LocalAgent"], ids=["runners", "localagent"])
def test_project_uses_released_sdk_without_local_override(project):
    config = tomllib.loads((project / "pyproject.toml").read_text())
    expected = "langbot-plugin==0.6.0b5" if project.name == "LocalAgent" else SDK_REQUIREMENT
    assert expected in config["project"]["dependencies"]
    assert "langbot-plugin" not in config.get("tool", {}).get("uv", {}).get("sources", {})
