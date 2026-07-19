from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from langbot_plugin.cli.commands.runplugin import should_load_artifact_dotenv
from langbot_plugin.entities.io.context import InstallationBinding, PluginWorkerPolicy
from langbot_plugin.runtime.plugin.artifact import PluginArtifactStore
from langbot_plugin.runtime.plugin.dependency_environment import (
    DependencyEnvironmentStaging,
    PluginDependencyEnvironment,
)
from langbot_plugin.runtime.plugin import worker_launcher as worker_launcher_module
from langbot_plugin.runtime.plugin.worker_launcher import (
    PluginWorkerLaunchSpec,
    PluginWorkerLauncher,
)
from langbot_plugin.runtime.security import (
    PLUGIN_REGISTRATION_CAPABILITY_ENV,
    PLUGIN_RUNTIME_PROFILE_ENV,
)


def _policy(*, require_hard_limits=True) -> PluginWorkerPolicy:
    return PluginWorkerPolicy(
        max_cpus=1.5,
        max_memory_mb=384,
        max_pids=73,
        max_open_files=211,
        max_file_size_mb=97,
        require_hard_limits=require_hard_limits,
    )


def _launch_spec(tmp_path) -> PluginWorkerLaunchSpec:
    package_io = io.BytesIO()
    with zipfile.ZipFile(package_io, "w") as archive:
        archive.writestr(
            "manifest.yaml",
            """
kind: Plugin
metadata:
  author: tester
  name: demo
  version: 1.0.0
spec:
  worker:
    max_cpus: 999
    max_memory_mb: 999999
""",
        )
    package = package_io.getvalue()
    digest = hashlib.sha256(package).hexdigest()
    binding = InstallationBinding(
        instance_uuid="instance-1",
        workspace_uuid="workspace-a",
        placement_generation=1,
        installation_uuid="installation-a",
        runtime_revision=1,
        artifact_digest=digest,
    )
    store = PluginArtifactStore(tmp_path / "plugin-runtime")
    artifact = store.install_package(package, digest)
    dependency_root = tmp_path / "plugin-runtime" / "environment"
    dependency_path = dependency_root / "site-packages"
    dependency_path.mkdir(parents=True)
    return PluginWorkerLaunchSpec(
        binding=binding,
        artifact=artifact,
        paths=store.ensure_installation_paths(binding),
        registration_capability="capability-value",
        dependency_environment=PluginDependencyEnvironment(
            digest="b" * 64,
            artifact_digest=digest,
            requirements_digest="c" * 64,
            runtime_fingerprint="d" * 64,
            root_path=dependency_root,
            site_packages_path=dependency_path,
        ),
    )


def test_shared_launcher_maps_only_trusted_policy_to_nsjail(tmp_path):
    python_prefix = tmp_path / "runtime" / ".venv"
    python_executable = python_prefix / "bin" / "python"
    python_executable.parent.mkdir(parents=True)
    python_executable.touch()
    launcher = PluginWorkerLauncher(
        nsjail_path="/usr/bin/nsjail",
        cgroup_v2_available=True,
        platform="linux",
        python_executable=str(python_executable),
        python_prefix=str(python_prefix),
    )
    launcher.configure(_policy(), "shared")

    args = launcher.build_nsjail_args(_launch_spec(tmp_path))

    assert args[args.index("--cgroup_mem_max") + 1] == str(384 * 1024 * 1024)
    assert args[args.index("--cgroup_pids_max") + 1] == "73"
    assert args[args.index("--cgroup_cpu_ms_per_sec") + 1] == "1500"
    assert args[args.index("--rlimit_nofile") + 1] == "211"
    assert args[args.index("--rlimit_fsize") + 1] == "97"
    assert "999" not in args
    assert "999999" not in args
    assert any(value.endswith(":/plugin") for value in args)
    assert any(value.endswith(":/plugin-dependencies") for value in args)
    assert any(value.endswith(":/home") for value in args)
    assert any(value.endswith(":/tmp") for value in args)
    assert any(value.endswith(":/data") for value in args)
    assert f"{python_prefix}:{python_prefix}" in args
    assert args[args.index("--") + 1] == str(python_executable)
    assert f"{PLUGIN_RUNTIME_PROFILE_ENV}=shared" in args
    assert f"{PLUGIN_REGISTRATION_CAPABILITY_ENV}=capability-value" in args
    assert "PYTHONPATH=/plugin-dependencies" in args
    assert "PYTHONDONTWRITEBYTECODE=1" in args


def test_dependency_preparation_uses_isolated_writable_staging_only(tmp_path):
    python_prefix = tmp_path / "runtime" / ".venv"
    python_executable = python_prefix / "bin" / "python"
    python_executable.parent.mkdir(parents=True)
    python_executable.touch()
    staging_root = tmp_path / "staging"
    staging = DependencyEnvironmentStaging(
        root_path=staging_root,
        site_packages_path=staging_root / "site-packages",
        scratch_path=staging_root / ".scratch",
        jail_root_path=staging_root / ".scratch" / "root",
        tmp_path=staging_root / ".scratch" / "tmp",
    )
    staging.site_packages_path.mkdir(parents=True)
    staging.jail_root_path.mkdir(parents=True)
    staging.tmp_path.mkdir(parents=True)
    launcher = PluginWorkerLauncher(
        nsjail_path="/usr/bin/nsjail",
        cgroup_v2_available=True,
        platform="linux",
        python_executable=str(python_executable),
        python_prefix=str(python_prefix),
    )
    launcher.configure(_policy(), "shared")

    args = launcher.build_dependency_prepare_nsjail_args(
        staging,
        ["third-party-demo==1.0.0"],
    )

    assert f"{staging.site_packages_path}:/dependency-env" in args
    assert f"{staging.tmp_path}:/tmp" in args
    assert "--ignore-installed" in args
    assert "--target" in args
    assert args[args.index("--target") + 1] == "/dependency-env"
    assert "-r" in args
    assert args[args.index("-r") + 1] == "/tmp/requirements.txt"
    assert (staging.tmp_path / "requirements.txt").read_text(encoding="utf-8") == (
        "third-party-demo==1.0.0\n"
    )
    assert "third-party-demo==1.0.0" not in args
    assert not any(value.endswith(":/plugin") for value in args)


def test_shared_launcher_fails_without_nsjail_or_required_cgroup():
    no_nsjail = PluginWorkerLauncher(
        nsjail_path="",
        cgroup_v2_available=True,
        platform="linux",
    )
    with pytest.raises(RuntimeError, match="require nsjail"):
        no_nsjail.configure(_policy(), "shared")

    no_cgroup = PluginWorkerLauncher(
        nsjail_path="/usr/bin/nsjail",
        cgroup_v2_available=False,
        platform="linux",
    )
    with pytest.raises(RuntimeError, match="delegated cgroup v2"):
        no_cgroup.configure(_policy(require_hard_limits=True), "shared")


def test_shared_launcher_rejects_unmounted_python_executable(tmp_path):
    python_prefix = tmp_path / "runtime" / ".venv"
    python_prefix.mkdir(parents=True)
    python_executable = tmp_path / "other" / "python"
    python_executable.parent.mkdir()
    python_executable.touch()
    launcher = PluginWorkerLauncher(
        nsjail_path="/usr/bin/nsjail",
        cgroup_v2_available=True,
        platform="linux",
        python_executable=str(python_executable),
        python_prefix=str(python_prefix),
    )

    with pytest.raises(RuntimeError, match="inside its mounted prefix"):
        launcher.configure(_policy(), "shared")


def test_shared_launcher_recreates_system_symlinks_instead_of_binding_them(
    tmp_path, monkeypatch
):
    host_root = tmp_path / "host"
    (host_root / "usr" / "bin").mkdir(parents=True)
    host_link = host_root / "bin"
    host_link.symlink_to("usr/bin")
    monkeypatch.setattr(
        worker_launcher_module, "_READONLY_SYSTEM_MOUNTS", (str(host_link),)
    )
    monkeypatch.setattr(worker_launcher_module, "_READONLY_ETC_FILES", ())

    launcher = PluginWorkerLauncher(
        nsjail_path="/usr/bin/nsjail",
        cgroup_v2_available=True,
        platform="linux",
    )
    launcher.configure(_policy(), "shared")
    launch_spec = _launch_spec(tmp_path / "state")
    args = launcher.build_nsjail_args(launch_spec)

    jail_link = launch_spec.paths.jail_root_path / str(host_link).lstrip("/")
    assert jail_link.is_symlink()
    assert jail_link.readlink() == host_link.readlink()
    assert f"{host_link}:{host_link}" not in args


def test_artifact_dotenv_is_disabled_only_for_shared_profile():
    assert should_load_artifact_dotenv("oss_dev") is True
    assert should_load_artifact_dotenv("") is True
    assert should_load_artifact_dotenv("shared") is False
