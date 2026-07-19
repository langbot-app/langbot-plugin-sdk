from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from langbot_plugin.entities.io.context import (
    InstallationBinding,
    PluginInstallationDesiredState,
    PluginWorkerPolicy,
    RuntimeIdentity,
)
from langbot_plugin.runtime.context import RuntimeContext
from langbot_plugin.runtime.plugin.artifact import PluginArtifactStore
from langbot_plugin.runtime.plugin.dependency_environment import (
    DependencyEnvironmentPreparationError,
    PluginDependencyEnvironment,
)
from langbot_plugin.runtime.plugin.mgr import PluginManager


def _package(
    *,
    body: str = "VALUE = 1",
    requirements: str | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "manifest.yaml",
            """
kind: Plugin
metadata:
  author: tester
  name: demo
  version: 1.0.0
spec: {}
""",
        )
        archive.writestr("main.py", body)
        if requirements is not None:
            archive.writestr("requirements.txt", requirements)
    return output.getvalue()


def _binding(
    installation_uuid: str,
    digest: str,
    *,
    workspace_uuid: str,
    generation: int = 1,
    revision: int = 1,
) -> InstallationBinding:
    return InstallationBinding(
        instance_uuid="instance-1",
        workspace_uuid=workspace_uuid,
        placement_generation=generation,
        installation_uuid=installation_uuid,
        runtime_revision=revision,
        artifact_digest=digest,
    )


def _manager(tmp_path) -> tuple[RuntimeContext, PluginManager]:
    context = RuntimeContext()
    context.bind_runtime(
        RuntimeIdentity(instance_uuid="instance-1", runtime_id="runtime-1"),
        PluginWorkerPolicy(
            max_cpus=1.0,
            max_memory_mb=512,
            max_pids=128,
            max_open_files=256,
            max_file_size_mb=512,
            require_hard_limits=True,
        ),
        "shared",
    )
    manager = PluginManager(context)
    manager.artifact_store = PluginArtifactStore(tmp_path / "plugin-runtime")
    context.plugin_mgr = manager
    return context, manager


async def test_manager_indexes_same_artifact_installations_by_complete_binding(
    tmp_path,
):
    context, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    binding_a = _binding(
        "installation-a",
        digest,
        workspace_uuid="workspace-a",
    )
    binding_b = _binding(
        "installation-b",
        digest,
        workspace_uuid="workspace-b",
    )

    await manager.apply_plugin_installation(
        binding_a,
        artifact_package=package,
        enabled=False,
    )
    await manager.apply_plugin_installation(
        binding_b,
        artifact_package=package,
        enabled=False,
    )

    runtimes = manager.installation_runtimes
    assert set(runtimes) == {binding_a, binding_b}
    assert (
        runtimes[binding_a].artifact.code_path == runtimes[binding_b].artifact.code_path
    )
    assert runtimes[binding_a].paths.home_path != runtimes[binding_b].paths.home_path
    assert runtimes[binding_a].paths.tmp_path != runtimes[binding_b].paths.tmp_path
    assert runtimes[binding_a].paths.data_path != runtimes[binding_b].paths.data_path
    assert context.is_current_installation_binding(binding_a)
    assert context.is_current_installation_binding(binding_b)


async def test_new_revision_revokes_old_binding_and_stale_reapply_fails(tmp_path):
    context, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    old_binding = _binding(
        "installation-a",
        digest,
        workspace_uuid="workspace-a",
        revision=1,
    )
    new_binding = old_binding.model_copy(update={"runtime_revision": 2})

    await manager.apply_plugin_installation(
        old_binding,
        artifact_package=package,
        enabled=False,
    )
    await manager.apply_plugin_installation(new_binding, enabled=False)

    assert old_binding not in manager.installation_runtimes
    assert new_binding in manager.installation_runtimes
    assert not context.is_current_installation_binding(old_binding)
    assert context.is_current_installation_binding(new_binding)
    with pytest.raises(ValueError, match="stale"):
        await manager.apply_plugin_installation(old_binding, enabled=False)

    await manager.remove_plugin_installation(new_binding)
    with pytest.raises(ValueError, match="stale"):
        await manager.apply_plugin_installation(new_binding, enabled=False)


async def test_reconcile_revokes_absent_or_old_workers_even_if_artifact_missing(
    tmp_path,
):
    context, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    old_binding = _binding(
        "installation-a",
        digest,
        workspace_uuid="workspace-a",
    )
    missing_binding = old_binding.model_copy(
        update={"runtime_revision": 2, "artifact_digest": "b" * 64}
    )
    await manager.apply_plugin_installation(
        old_binding,
        artifact_package=package,
        enabled=False,
    )

    result = await manager.reconcile_plugin_installations(
        (PluginInstallationDesiredState(binding=missing_binding),)
    )

    assert result["removed"] == ["installation-a"]
    assert result["missing_artifacts"] == ["installation-a"]
    assert old_binding not in manager.installation_runtimes
    assert context.is_current_installation_binding(missing_binding)
    assert not context.is_current_installation_binding(old_binding)


def test_registration_capability_is_one_use_and_bound_to_complete_tuple(tmp_path):
    context, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    binding = _binding(
        "installation-a",
        digest,
        workspace_uuid="workspace-a",
    )
    context.activate_installation_binding(binding)
    capability = manager._issue_registration_capability(
        plugin_author="tester",
        plugin_name="demo",
        plugin_path="/verified/code",
        binding=binding,
    )

    registration = manager._consume_registration_capability(
        capability,
        plugin_author="tester",
        plugin_name="demo",
    )

    assert registration.binding == binding
    with pytest.raises(ValueError, match="invalid or already used"):
        manager._consume_registration_capability(
            capability,
            plugin_author="tester",
            plugin_name="demo",
        )


async def test_shared_apply_prepares_dependency_environment_before_worker_launch(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package(requirements="third-party-demo==1.0.0\n")
    digest = hashlib.sha256(package).hexdigest()
    binding = _binding(
        "installation-a",
        digest,
        workspace_uuid="workspace-a",
    )
    order: list[str] = []

    async def prepare(store, artifact):
        order.append("prepare")
        root = store.base_path / "test-environment"
        site_packages = root / "site-packages"
        site_packages.mkdir(parents=True)
        return PluginDependencyEnvironment(
            digest="b" * 64,
            artifact_digest=artifact.digest,
            requirements_digest="c" * 64,
            runtime_fingerprint="d" * 64,
            root_path=root,
            site_packages_path=site_packages,
        )

    def schedule(runtime):
        assert runtime.dependency_environment is not None
        order.append("launch")

    monkeypatch.setattr(
        manager.worker_launcher,
        "prepare_dependency_environment",
        prepare,
    )
    monkeypatch.setattr(manager, "_schedule_installation_worker", schedule)

    result = await manager.apply_plugin_installation(
        binding,
        artifact_package=package,
        enabled=True,
    )

    assert order == ["prepare", "launch"]
    assert result["state"] == "starting"
    assert result["dependency_environment_digest"] == "b" * 64


async def test_shared_dependency_failure_is_explicit_and_same_revision_can_retry(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package(requirements="third-party-demo==1.0.0\n")
    digest = hashlib.sha256(package).hexdigest()
    binding = _binding(
        "installation-a",
        digest,
        workspace_uuid="workspace-a",
    )
    launch_count = 0

    async def fail_prepare(store, artifact):
        raise DependencyEnvironmentPreparationError("dependency download failed")

    def schedule(runtime):
        nonlocal launch_count
        launch_count += 1

    monkeypatch.setattr(
        manager.worker_launcher,
        "prepare_dependency_environment",
        fail_prepare,
    )
    monkeypatch.setattr(manager, "_schedule_installation_worker", schedule)

    failed = await manager.apply_plugin_installation(
        binding,
        artifact_package=package,
        enabled=True,
    )

    assert failed == {
        "installation_uuid": "installation-a",
        "state": "failed",
        "artifact_path": failed["artifact_path"],
        "error_code": "dependency_prepare_failed",
        "message": "dependency download failed",
    }
    assert launch_count == 0
    runtime = manager.installation_runtimes[binding]
    assert runtime.launch_task is None
    assert runtime.dependency_environment is None

    async def successful_prepare(store, artifact):
        root = store.base_path / "retry-environment"
        site_packages = root / "site-packages"
        site_packages.mkdir(parents=True)
        return PluginDependencyEnvironment(
            digest="e" * 64,
            artifact_digest=artifact.digest,
            requirements_digest="f" * 64,
            runtime_fingerprint="1" * 64,
            root_path=root,
            site_packages_path=site_packages,
        )

    monkeypatch.setattr(
        manager.worker_launcher,
        "prepare_dependency_environment",
        successful_prepare,
    )
    retried = await manager.apply_plugin_installation(binding, enabled=True)

    assert retried["state"] == "starting"
    assert retried["dependency_environment_digest"] == "e" * 64
    assert launch_count == 1


async def test_reconcile_reports_dependency_failure_without_worker_launch(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package(requirements="third-party-demo==1.0.0\n")
    digest = hashlib.sha256(package).hexdigest()
    binding = _binding(
        "installation-a",
        digest,
        workspace_uuid="workspace-a",
    )
    await manager.apply_plugin_installation(
        binding,
        artifact_package=package,
        enabled=False,
    )

    async def fail_prepare(store, artifact):
        raise DependencyEnvironmentPreparationError("dependency download failed")

    monkeypatch.setattr(
        manager.worker_launcher,
        "prepare_dependency_environment",
        fail_prepare,
    )

    result = await manager.reconcile_plugin_installations(
        (PluginInstallationDesiredState(binding=binding),)
    )

    assert result["failed_installations"] == [
        {
            "installation_uuid": "installation-a",
            "error_code": "dependency_prepare_failed",
            "message": "dependency download failed",
        }
    ]
    assert manager.installation_runtimes[binding].launch_task is None


async def test_oss_desired_state_keeps_legacy_worker_without_shared_environment(
    tmp_path,
    monkeypatch,
):
    context = RuntimeContext()
    context.bind_runtime(
        RuntimeIdentity(instance_uuid="instance-1", runtime_id="runtime-1"),
        PluginWorkerPolicy(
            max_cpus=1.0,
            max_memory_mb=512,
            max_pids=128,
            max_open_files=256,
            max_file_size_mb=512,
            require_hard_limits=False,
        ),
        "oss_dev",
    )
    manager = PluginManager(context)
    manager.artifact_store = PluginArtifactStore(tmp_path / "plugin-runtime")
    context.plugin_mgr = manager
    package = _package(requirements="third-party-demo==1.0.0\n")
    digest = hashlib.sha256(package).hexdigest()
    binding = _binding(
        "installation-a",
        digest,
        workspace_uuid="workspace-a",
    )
    scheduled = []

    def schedule(runtime):
        scheduled.append(runtime)

    monkeypatch.setattr(manager, "_schedule_installation_worker", schedule)

    result = await manager.apply_plugin_installation(
        binding,
        artifact_package=package,
        enabled=True,
    )

    assert result["state"] == "starting"
    assert "dependency_environment_digest" not in result
    assert len(scheduled) == 1
    assert scheduled[0].dependency_environment is None
