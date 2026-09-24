"""Shared-runtime release contract; run with the actual candidate SDK."""

import importlib.metadata
import tomllib
from pathlib import Path

import pytest
import yaml
from langbot_plugin.runtime.plugin.artifact import PluginArtifact
from langbot_plugin.runtime.plugin.dependency_environment import PluginDependencyEnvironmentStore

ROOT = Path(__file__).resolve().parents[1]


def test_shared_release_metadata_and_standalone_lock():
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())
    assert manifest["execution"].get("sharedRuntime") == "shared-runtime-v1"
    assert manifest["metadata"]["version"] == "0.1.10"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "langbot-plugin==0.6.1" in project["project"]["dependencies"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert [p["version"] for p in lock["package"] if p["name"] == "langbot-plugin"] == ["0.6.1"]


@pytest.mark.asyncio
async def test_real_sdk_dependency_admission(tmp_path):
    assert importlib.metadata.version("langbot-plugin") == "0.6.1"
    artifact = PluginArtifact("1" * 64, ROOT, ROOT, "langbot-team", "LocalAgent", "0.1.10")
    store = PluginDependencyEnvironmentStore(tmp_path)
    from langbot_plugin.entities.io.context import PluginWorkerPolicy
    from langbot_plugin.runtime.plugin.worker_launcher import PluginWorkerLauncher

    launcher = PluginWorkerLauncher()
    # Real SDK installer into a disposable target, not shared nsjail enforcement.
    launcher.configure(
        PluginWorkerPolicy(max_cpus=1, max_memory_mb=512, max_pids=32, max_open_files=128, max_file_size_mb=32),
        "oss_dev",
    )
    ready = await launcher.prepare_dependency_environment(store, artifact)
    assert store.get_ready(ready.digest) == ready
    assert not (ready.site_packages_path / "langbot_plugin").exists()
    assert (ready.site_packages_path / "pydantic").is_dir()
    assert await launcher.prepare_dependency_environment(store, artifact) == ready
