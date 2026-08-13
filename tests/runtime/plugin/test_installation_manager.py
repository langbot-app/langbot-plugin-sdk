from __future__ import annotations

import asyncio
import hashlib
import io
import stat
import threading
import zipfile
from types import SimpleNamespace
from unittest import mock

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
from langbot_plugin.runtime.plugin import mgr as manager_module


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
    assert stat.S_IMODE(runtimes[binding_a].paths.root_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(runtimes[binding_b].paths.root_path.stat().st_mode) == 0o700
    assert context.is_current_installation_binding(binding_a)
    assert context.is_current_installation_binding(binding_b)


async def test_desired_state_does_not_reject_on_aggregate_worker_capacity(
    tmp_path,
    monkeypatch,
):
    context, manager = _manager(tmp_path)
    context.worker_policy = context.worker_policy.model_copy(
        update={
            "max_workers": 1,
            "max_total_cpus": 1.0,
            "max_total_memory_mb": 512,
            "require_hard_limits": False,
        }
    )
    context.runtime_profile = "oss_dev"
    manager.configure_worker_runtime(context.worker_policy, "oss_dev")
    monkeypatch.setattr(manager, "_schedule_installation_worker", lambda _runtime: None)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    first = _binding("installation-a", digest, workspace_uuid="workspace-a")
    second = _binding("installation-b", digest, workspace_uuid="workspace-b")

    started = await manager.apply_plugin_installation(
        first,
        artifact_package=package,
        enabled=True,
    )
    second_started = await manager.apply_plugin_installation(second, enabled=True)
    replacement = await manager.apply_plugin_installation(
        _binding(
            "installation-a",
            digest,
            workspace_uuid="workspace-a",
            revision=2,
        ),
        enabled=True,
    )

    assert started["state"] == "starting"
    assert second_started["state"] == "starting"
    assert replacement["state"] == "starting"

    reconciled = await manager.reconcile_plugin_installations(
        (
            PluginInstallationDesiredState(
                binding=first.model_copy(update={"runtime_revision": 2})
            ),
            PluginInstallationDesiredState(binding=second),
        )
    )
    assert reconciled["applied"] == ["installation-a", "installation-b"]


async def test_installation_lifecycle_runs_dependency_preparation_concurrently_bounded(
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
            max_concurrent_restarts=2,
            require_hard_limits=True,
        ),
        "shared",
    )
    manager = PluginManager(context)
    manager.artifact_store = PluginArtifactStore(tmp_path / "plugin-runtime")
    context.plugin_mgr = manager
    package = _package(requirements="third-party-demo==1.0.0\n")
    digest = hashlib.sha256(package).hexdigest()
    first = _binding("installation-a", digest, workspace_uuid="workspace-a")
    second = _binding("installation-b", digest, workspace_uuid="workspace-b")
    third = _binding("installation-c", digest, workspace_uuid="workspace-c")
    await manager.apply_plugin_installation(
        first,
        artifact_package=package,
        enabled=False,
    )
    await manager.apply_plugin_installation(second, enabled=False)
    await manager.apply_plugin_installation(third, enabled=False)

    first_prepare_started = asyncio.Event()
    release_prepare = asyncio.Event()
    active_prepares = 0
    max_active_prepares = 0

    async def prepare(store, artifact):
        nonlocal active_prepares, max_active_prepares
        active_prepares += 1
        max_active_prepares = max(max_active_prepares, active_prepares)
        first_prepare_started.set()
        try:
            await release_prepare.wait()
        finally:
            active_prepares -= 1
        root = store.base_path / "serialized-environment"
        site_packages = root / "site-packages"
        site_packages.mkdir(parents=True, exist_ok=True)
        return PluginDependencyEnvironment(
            digest="b" * 64,
            artifact_digest=artifact.digest,
            requirements_digest="c" * 64,
            runtime_fingerprint="d" * 64,
            root_path=root,
            site_packages_path=site_packages,
        )

    monkeypatch.setattr(
        manager.worker_launcher,
        "prepare_dependency_environment",
        prepare,
    )
    monkeypatch.setattr(manager, "_schedule_installation_worker", lambda _runtime: None)

    first_task = asyncio.create_task(
        manager.apply_plugin_installation(first, enabled=True)
    )
    await first_prepare_started.wait()
    second_task = asyncio.create_task(
        manager.apply_plugin_installation(second, enabled=True)
    )

    async def wait_for_two_prepares():
        while active_prepares < 2:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_two_prepares(), timeout=1)
    third_task = asyncio.create_task(
        manager.apply_plugin_installation(third, enabled=True)
    )
    await asyncio.sleep(0)

    assert active_prepares == 2
    assert not third_task.done()
    release_prepare.set()
    await asyncio.gather(first_task, second_task, third_task)
    assert max_active_prepares == 2


async def test_installation_lock_waiter_does_not_consume_lifecycle_capacity(
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
            max_concurrent_restarts=2,
            require_hard_limits=True,
        ),
        "shared",
    )
    manager = PluginManager(context)
    manager.artifact_store = PluginArtifactStore(tmp_path / "plugin-runtime")
    context.plugin_mgr = manager
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    first = _binding("installation-a", digest, workspace_uuid="workspace-a")
    other = _binding("installation-b", digest, workspace_uuid="workspace-b")
    entered = asyncio.Event()
    other_entered = asyncio.Event()
    release = asyncio.Event()

    original = manager._apply_plugin_installation_locked

    async def blocked(binding, **kwargs):
        if binding.installation_uuid == "installation-a" and not entered.is_set():
            entered.set()
            await release.wait()
        elif binding.installation_uuid == "installation-b":
            other_entered.set()
        return await original(binding, **kwargs)

    monkeypatch.setattr(manager, "_apply_plugin_installation_locked", blocked)
    first_task = asyncio.create_task(
        manager.apply_plugin_installation(
            first,
            artifact_package=package,
            enabled=False,
        )
    )
    await entered.wait()
    waiter = asyncio.create_task(
        manager.apply_plugin_installation(first, enabled=False)
    )
    other_task = asyncio.create_task(
        manager.apply_plugin_installation(other, enabled=False)
    )

    await asyncio.wait_for(other_entered.wait(), timeout=1)
    release.set()
    await asyncio.gather(first_task, waiter, other_task)


async def test_installation_lock_entry_survives_waiter_handoff(tmp_path, monkeypatch):
    _, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    binding = _binding("installation-a", digest, workspace_uuid="workspace-a")
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    original = manager._apply_plugin_installation_locked

    async def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(manager, "_apply_plugin_installation_locked", blocked)
    first = asyncio.create_task(
        manager.apply_plugin_installation(
            binding,
            artifact_package=package,
            enabled=False,
        )
    )
    await entered.wait()
    second = asyncio.create_task(
        manager.apply_plugin_installation(binding, enabled=False)
    )
    await asyncio.sleep(0)

    assert calls == 1
    release.set()
    await asyncio.gather(first, second)

    assert calls == 2
    assert manager._installation_operation_locks == {}


async def test_reconcile_absent_removal_serializes_with_direct_apply_for_same_installation(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    old_binding = _binding("installation-a", digest, workspace_uuid="workspace-a")
    new_binding = old_binding.model_copy(update={"runtime_revision": 2})
    await manager.apply_plugin_installation(
        old_binding,
        artifact_package=package,
        enabled=False,
    )
    revoke_started = asyncio.Event()
    release_revoke = asyncio.Event()
    original_revoke = manager._revoke_installation_runtime

    async def blocked_revoke(binding):
        revoke_started.set()
        await release_revoke.wait()
        await original_revoke(binding)

    monkeypatch.setattr(manager, "_revoke_installation_runtime", blocked_revoke)

    reconcile_task = asyncio.create_task(manager.reconcile_plugin_installations(()))
    await revoke_started.wait()
    direct_apply = asyncio.create_task(
        manager.apply_plugin_installation(new_binding, enabled=False)
    )
    await asyncio.sleep(0)

    assert not direct_apply.done()

    release_revoke.set()
    await reconcile_task
    result = await asyncio.wait_for(direct_apply, timeout=1)

    assert result["state"] == "disabled"
    assert manager._active_binding_by_uuid["installation-a"] == new_binding


async def test_reconcile_watermark_gc_does_not_delete_newer_direct_state(
    tmp_path,
    monkeypatch,
):
    context, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    old_binding = _binding("installation-a", digest, workspace_uuid="workspace-a")
    new_binding = old_binding.model_copy(update={"runtime_revision": 2})
    await manager.apply_plugin_installation(
        old_binding,
        artifact_package=package,
        enabled=False,
    )
    await manager.remove_plugin_installation(old_binding)
    gc_started = asyncio.Event()
    release_gc = asyncio.Event()
    original_gc = context.reconcile_installation_watermarks

    async def blocked_gc(authoritative_bindings):
        gc_started.set()
        await release_gc.wait()
        original_gc(authoritative_bindings)

    monkeypatch.setattr(manager, "_reconcile_installation_watermarks_locked", blocked_gc)

    reconcile_task = asyncio.create_task(manager.reconcile_plugin_installations(()))
    await gc_started.wait()
    direct_apply = asyncio.create_task(
        manager.apply_plugin_installation(new_binding, enabled=False)
    )
    await asyncio.sleep(0)

    assert not direct_apply.done()

    release_gc.set()
    await reconcile_task
    await asyncio.wait_for(direct_apply, timeout=1)

    assert context.is_current_installation_binding(new_binding)
    with pytest.raises(ValueError, match="stale"):
        await manager.apply_plugin_installation(old_binding, enabled=False)


def test_pending_registration_capability_uses_independent_policy_bound(tmp_path):
    context, manager = _manager(tmp_path)
    context.worker_policy = context.worker_policy.model_copy(
        update={
            "max_workers": 1,
            "max_total_cpus": 1.0,
            "max_total_memory_mb": 512,
            "max_pending_registrations": 2,
        }
    )
    binding = _binding("installation-a", "a" * 64, workspace_uuid="workspace-a")
    context.activate_installation_binding(binding)

    issued = [
        manager._issue_registration_capability(
            plugin_author="tester",
            plugin_name="demo",
            plugin_path="/verified/code",
            binding=binding,
        )
        for _ in range(2)
    ]

    assert len(issued) == 2
    with pytest.raises(RuntimeError, match="capacity reached"):
        manager._issue_registration_capability(
            plugin_author="tester",
            plugin_name="demo",
            plugin_path="/verified/code",
            binding=binding,
        )


async def test_authoritative_reconcile_reclaims_inactive_historical_watermarks(
    tmp_path,
):
    context, manager = _manager(tmp_path)
    context.worker_policy = context.worker_policy.model_copy(
        update={"max_installations": 1}
    )
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    removed_binding = _binding("installation-a", digest, workspace_uuid="workspace-a")
    next_binding = _binding("installation-b", digest, workspace_uuid="workspace-b")

    await manager.apply_plugin_installation(
        removed_binding,
        artifact_package=package,
        enabled=False,
    )
    await manager.remove_plugin_installation(removed_binding)
    with pytest.raises(ValueError, match="fence capacity"):
        await manager.apply_plugin_installation(next_binding, enabled=False)

    result = await manager.reconcile_plugin_installations(())

    assert result["applied"] == []
    await manager.apply_plugin_installation(next_binding, enabled=False)
    assert context.is_current_installation_binding(next_binding)


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


async def test_reconcile_batch_failure_cancels_and_joins_sibling_mutations(
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
            max_concurrent_restarts=2,
            require_hard_limits=True,
        ),
        "shared",
    )
    manager = PluginManager(context)
    manager.artifact_store = PluginArtifactStore(tmp_path / "plugin-runtime")
    context.plugin_mgr = manager
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    first = _binding("installation-a", digest, workspace_uuid="workspace-a")
    second = _binding("installation-b", digest, workspace_uuid="workspace-b")
    await manager.apply_plugin_installation(
        first,
        artifact_package=package,
        enabled=False,
    )
    await manager.apply_plugin_installation(second, enabled=False)
    sibling_started = asyncio.Event()
    sibling_cancelled = asyncio.Event()
    original_apply = manager._apply_plugin_installation_locked

    async def apply_or_fail(binding, **kwargs):
        if binding.installation_uuid == "installation-a":
            raise RuntimeError("forced partial failure")
        if binding.installation_uuid == "installation-b":
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sibling_cancelled.set()
                raise
        return await original_apply(binding, **kwargs)

    monkeypatch.setattr(manager, "_apply_plugin_installation_locked", apply_or_fail)

    with pytest.raises(RuntimeError, match="forced partial failure"):
        await manager.reconcile_plugin_installations(
            (
                PluginInstallationDesiredState(binding=first),
                PluginInstallationDesiredState(binding=second),
            )
        )

    assert sibling_started.is_set()
    assert sibling_cancelled.is_set()
    assert manager._installation_operation_locks == {}
    assert not manager._reconcile_operation_lock.locked()


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


async def test_installation_supervisor_restarts_crashed_enabled_worker(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package()
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
    runtime = manager.installation_runtimes[binding]
    runtime.enabled = True
    second_generation_started = asyncio.Event()
    calls = 0

    async def launch(candidate):
        nonlocal calls
        assert candidate == binding
        calls += 1
        if calls == 1:
            raise RuntimeError("worker crashed")
        runtime.ready_event.set()
        second_generation_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(manager, "launch_plugin_installation", launch)
    monkeypatch.setattr(
        "langbot_plugin.runtime.plugin.mgr._PLUGIN_RESTART_INITIAL_DELAY_SEC",
        0,
    )

    manager._schedule_installation_worker(runtime)
    first_supervisor = runtime.launch_task
    manager._schedule_installation_worker(runtime)
    assert runtime.launch_task is first_supervisor
    await asyncio.wait_for(second_generation_started.wait(), timeout=1)

    async def wait_for_launches_to_finish():
        while manager.restart_coordinator.snapshot()["active_launches"]:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_launches_to_finish(), timeout=1)

    assert calls == 2
    assert runtime.launch_task is not None
    assert runtime.launch_task in manager.plugin_run_tasks
    assert manager.restart_coordinator.snapshot()["active_launches"] == 0
    assert manager.restart_coordinator.snapshot()["restart_failures_total"] == 1

    await manager._stop_installation_worker(runtime)

    assert runtime.launch_task is None
    assert manager.plugin_run_tasks == []


async def test_installation_worker_ready_timeout_cancels_hung_process(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package()
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
    runtime = manager.installation_runtimes[binding]
    runtime.enabled = True
    cancelled = asyncio.Event()

    async def launch(_candidate):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(manager, "launch_plugin_installation", launch)
    monkeypatch.setattr(manager_module, "_PLUGIN_READY_TIMEOUT_SEC", 0.01)

    with pytest.raises(TimeoutError, match="did not become ready"):
        await manager._run_installation_worker_attempt(runtime, None)

    assert cancelled.is_set()


async def test_first_installation_launches_are_globally_bounded(
    tmp_path,
    monkeypatch,
):
    context, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    first = _binding("installation-a", digest, workspace_uuid="workspace-a")
    second = _binding("installation-b", digest, workspace_uuid="workspace-b")
    await manager.apply_plugin_installation(
        first,
        artifact_package=package,
        enabled=False,
    )
    await manager.apply_plugin_installation(second, enabled=False)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    started: list[str] = []

    async def launch(candidate):
        started.append(candidate.installation_uuid)
        runtime = manager.installation_runtimes[candidate]
        runtime.ready_event.set()
        if candidate == first:
            first_started.set()
            await release_first.wait()
        runtime.enabled = False

    monkeypatch.setattr(manager, "launch_plugin_installation", launch)

    first_runtime = manager.installation_runtimes[first]
    second_runtime = manager.installation_runtimes[second]
    first_runtime.enabled = True
    second_runtime.enabled = True
    manager._schedule_installation_worker(first_runtime)
    await first_started.wait()
    manager._schedule_installation_worker(second_runtime)
    await asyncio.sleep(0)

    assert started == ["installation-a"]
    release_first.set()
    await asyncio.wait_for(second_runtime.launch_task, timeout=1)

    assert started == ["installation-a", "installation-b"]
    await manager._stop_installation_worker(first_runtime)
    await manager._stop_installation_worker(second_runtime)


async def test_unrelated_artifact_publications_do_not_block_each_other(
    tmp_path,
    monkeypatch,
):
    context, manager = _manager(tmp_path)
    first_package = _package(body="VALUE = 1")
    second_package = _package(body="VALUE = 2")
    first_digest = hashlib.sha256(first_package).hexdigest()
    second_digest = hashlib.sha256(second_package).hexdigest()
    first = _binding("installation-a", first_digest, workspace_uuid="workspace-a")
    second = _binding("installation-b", second_digest, workspace_uuid="workspace-b")
    install_started = threading.Event()
    release_install = threading.Event()
    original_install = manager.artifact_store.install_package

    def install_package(package, expected_digest):
        if expected_digest == first_digest:
            install_started.set()
            release_install.wait(timeout=5)
        return original_install(package, expected_digest)

    monkeypatch.setattr(manager.artifact_store, "install_package", install_package)

    first_task = asyncio.create_task(
        manager.apply_plugin_installation(
            first,
            artifact_package=first_package,
            enabled=False,
        )
    )
    async def wait_for_install_started():
        while not install_started.is_set():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_install_started(), timeout=1)
    second_task = asyncio.create_task(
        manager.apply_plugin_installation(
            second,
            artifact_package=second_package,
            enabled=False,
        )
    )

    second_result = await asyncio.wait_for(second_task, timeout=1)

    release_install.set()
    await asyncio.wait_for(first_task, timeout=1)
    assert second_result["state"] == "disabled"
    assert context.is_current_installation_binding(second)


async def test_identical_artifact_publication_is_deduped(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    first = _binding("installation-a", digest, workspace_uuid="workspace-a")
    second = _binding("installation-b", digest, workspace_uuid="workspace-b")
    install_calls = 0
    original_install = manager.artifact_store.install_package

    def install_package(package, expected_digest):
        nonlocal install_calls
        install_calls += 1
        return original_install(package, expected_digest)

    monkeypatch.setattr(manager.artifact_store, "install_package", install_package)

    await asyncio.gather(
        manager.apply_plugin_installation(
            first,
            artifact_package=package,
            enabled=False,
        ),
        manager.apply_plugin_installation(
            second,
            artifact_package=package,
            enabled=False,
        ),
    )

    assert install_calls == 1


def test_runtime_health_reports_identity_free_installation_state_counts(tmp_path):
    context, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()

    for installation_uuid, state in (
        ("installation-running", "running"),
        ("installation-starting", "starting"),
        ("installation-failed", "failed"),
        ("installation-disabled", "disabled"),
    ):
        binding = _binding(installation_uuid, digest, workspace_uuid=installation_uuid)
        artifact = manager.artifact_store.install_package(package, digest)
        paths = manager.artifact_store.ensure_installation_paths(binding)
        manager._installations[binding] = manager_module.PluginInstallationRuntime(
            binding=binding,
            artifact=artifact,
            paths=paths,
            enabled=state != "disabled",
            state=state,
        )

    stats = context.get_runtime_resource_stats()

    assert stats["installation_states"] == {
        "running": 1,
        "starting": 1,
        "failed": 1,
        "disabled": 1,
    }
    assert "installation-running" not in str(stats)


async def test_installation_launch_failure_is_recorded_locally(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package()
    digest = hashlib.sha256(package).hexdigest()
    binding = _binding("installation-a", digest, workspace_uuid="workspace-a")
    await manager.apply_plugin_installation(
        binding,
        artifact_package=package,
        enabled=False,
    )
    runtime = manager.installation_runtimes[binding]
    runtime.enabled = True

    async def launch(_candidate):
        raise RuntimeError("worker crashed before ready")

    monkeypatch.setattr(manager, "launch_plugin_installation", launch)
    permit = await manager.restart_coordinator.acquire(binding.installation_uuid)

    try:
        with pytest.raises(RuntimeError, match="worker crashed"):
            await manager._run_installation_worker_attempt(runtime, permit)
    finally:
        await permit.abandon()

    assert runtime.state == "failed"
    assert runtime.error_code == "worker_launch_failed"
    assert "worker crashed before ready" in str(runtime.error_message)


async def test_installation_supervisor_does_not_restart_fenced_worker(
    tmp_path,
    monkeypatch,
):
    context, manager = _manager(tmp_path)
    package = _package()
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
    runtime = manager.installation_runtimes[binding]
    runtime.enabled = True
    calls = 0

    async def launch(candidate):
        nonlocal calls
        calls += 1
        context.deactivate_installation_binding(candidate)

    monkeypatch.setattr(manager, "launch_plugin_installation", launch)

    manager._schedule_installation_worker(runtime)
    task = runtime.launch_task
    assert task is not None
    await task
    await asyncio.sleep(0)

    assert calls == 1
    assert runtime.launch_task is None
    assert task not in manager.plugin_run_tasks


async def test_launch_installation_builds_private_scoped_handler(
    tmp_path,
    monkeypatch,
):
    _, manager = _manager(tmp_path)
    package = _package()
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
    runtime = manager.installation_runtimes[binding]
    dependency_root = tmp_path / "dependency"
    dependency_site_packages = dependency_root / "site-packages"
    dependency_site_packages.mkdir(parents=True)
    runtime.dependency_environment = PluginDependencyEnvironment(
        digest="b" * 64,
        artifact_digest=digest,
        requirements_digest="c" * 64,
        runtime_fingerprint="d" * 64,
        root_path=dependency_root,
        site_packages_path=dependency_site_packages,
    )
    runtime.enabled = True
    connection = object()
    process = object()
    captured = {}

    class FakeController:
        def __init__(self):
            self.process = process

        async def run(self, callback):
            await callback(connection)

    class FakePluginHandler:
        def __init__(self, handler_connection, context, **kwargs):
            captured["handler_connection"] = handler_connection
            captured["handler_context"] = context
            captured["handler_kwargs"] = kwargs

    def create_controller(spec):
        captured["launch_spec"] = spec
        return FakeController()

    async def add_plugin_handler(handler):
        captured["handler"] = handler

    monkeypatch.setattr(
        manager.worker_launcher,
        "create_controller",
        create_controller,
    )
    monkeypatch.setattr(
        manager_module.runtime_plugin_handler_cls,
        "PluginConnectionHandler",
        FakePluginHandler,
    )
    monkeypatch.setattr(manager, "add_plugin_handler", add_plugin_handler)

    await manager.launch_plugin_installation(binding)

    assert captured["launch_spec"].binding == binding
    assert captured["launch_spec"].dependency_environment is (
        runtime.dependency_environment
    )
    assert captured["handler_connection"] is connection
    assert captured["handler_context"] is manager.context
    assert captured["handler_kwargs"]["stdio_process"] is process
    assert captured["handler_kwargs"]["file_storage_dir"] == str(
        runtime.paths.root_path / "rpc-transfer"
    )
    assert captured["handler_kwargs"]["max_file_bytes"] == 512 * 1024 * 1024
    assert runtime.plugin_handler is captured["handler"]
    assert manager._pending_registrations == {}


async def test_stop_installation_worker_reaps_handler_process_and_task(
    tmp_path,
):
    _, manager = _manager(tmp_path)
    package = _package()
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
    runtime = manager.installation_runtimes[binding]

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.waited = False

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            self.returncode = 0
            return self.returncode

    process = FakeProcess()
    plugin_container = object()
    handler = SimpleNamespace(
        cancel_inflight_messages=mock.Mock(),
        shutdown_plugin=mock.AsyncMock(side_effect=RuntimeError("already exited")),
        conn=SimpleNamespace(close=mock.AsyncMock()),
        stdio_process=process,
    )
    runtime.plugin_handler = handler
    runtime.plugin_container = plugin_container
    manager.plugin_handlers.append(handler)
    manager._binding_by_container_id[id(plugin_container)] = binding
    launch_task = asyncio.create_task(asyncio.Event().wait())
    runtime.launch_task = launch_task

    await manager._stop_installation_worker(runtime)

    handler.cancel_inflight_messages.assert_called_once_with()
    handler.shutdown_plugin.assert_awaited_once_with()
    handler.conn.close.assert_awaited_once_with()
    assert process.terminated is False
    assert process.killed is False
    assert process.waited is True
    assert handler not in manager.plugin_handlers
    assert id(plugin_container) not in manager._binding_by_container_id
    assert launch_task.cancelled()
    assert runtime.plugin_handler is None
    assert runtime.plugin_container is None
    assert runtime.launch_task is None


@pytest.mark.parametrize(
    "lifecycle_operation",
    ["remove", "reconcile", "shutdown"],
)
async def test_installation_lifecycle_routes_allow_graceful_worker_exit(
    tmp_path,
    lifecycle_operation,
):
    _, manager = _manager(tmp_path)
    package = _package()
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
    runtime = manager.installation_runtimes[binding]
    events: list[str] = []

    class GracefulProcess:
        def __init__(self):
            self.returncode = None
            self.terminate_calls = 0
            self.kill_calls = 0

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1

        async def wait(self):
            events.append("wait")
            self.returncode = 0
            return self.returncode

    process = GracefulProcess()

    async def shutdown_plugin():
        events.append("shutdown")

    async def close_connection():
        events.append("close")

    handler = SimpleNamespace(
        cancel_inflight_messages=lambda: events.append("cancel"),
        shutdown_plugin=shutdown_plugin,
        conn=SimpleNamespace(close=close_connection),
        stdio_process=process,
    )
    runtime.plugin_handler = handler
    manager.plugin_handlers.append(handler)

    if lifecycle_operation == "remove":
        await manager.remove_plugin_installation(binding)
    elif lifecycle_operation == "reconcile":
        await manager.reconcile_plugin_installations(())
    else:
        await manager.shutdown_all_plugins()

    assert events == ["cancel", "shutdown", "close", "wait"]
    assert process.terminate_calls == 0
    assert process.kill_calls == 0
    assert handler not in manager.plugin_handlers
    assert runtime.plugin_handler is None


async def test_launch_installation_fails_closed_without_current_ready_runtime(
    tmp_path,
):
    context, manager = _manager(tmp_path)
    package = _package()
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
    runtime = manager.installation_runtimes[binding]

    await manager.launch_plugin_installation(binding)

    runtime.enabled = True
    with pytest.raises(ValueError, match="dependency environment"):
        await manager.launch_plugin_installation(binding)

    context.deactivate_installation_binding(binding)
    with pytest.raises(ValueError, match="no longer current"):
        await manager.launch_plugin_installation(binding)
