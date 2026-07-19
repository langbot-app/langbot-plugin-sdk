from __future__ import annotations

import os
import pathlib
import shutil
import sys
from dataclasses import dataclass
from typing import Literal

from langbot_plugin.entities.io.context import InstallationBinding, PluginWorkerPolicy
from langbot_plugin.runtime.io.controllers.stdio import (
    client as stdio_client_controller,
)
from langbot_plugin.runtime.plugin.artifact import (
    PluginArtifact,
    PluginInstallationPaths,
)
from langbot_plugin.runtime.security import (
    PLUGIN_REGISTRATION_CAPABILITY_ENV,
    PLUGIN_RUNTIME_PROFILE_ENV,
)
from langbot_plugin.utils.platform import get_platform


_READONLY_SYSTEM_MOUNTS = (
    "/bin",
    "/lib",
    "/lib64",
    "/sbin",
    "/usr",
)
_READONLY_ETC_FILES = (
    "/etc/hosts",
    "/etc/nsswitch.conf",
    "/etc/resolv.conf",
    "/etc/ssl",
)
_DEV_NODES = ("/dev/null", "/dev/random", "/dev/urandom")


@dataclass(frozen=True, slots=True)
class PluginWorkerLaunchSpec:
    binding: InstallationBinding
    artifact: PluginArtifact
    paths: PluginInstallationPaths
    registration_capability: str


class PluginWorkerLauncher:
    """Build isolated worker processes exclusively from trusted Runtime policy."""

    def __init__(
        self,
        *,
        nsjail_path: str | None = None,
        cgroup_v2_available: bool | None = None,
        platform: str | None = None,
        python_executable: str | None = None,
        python_prefix: str | None = None,
    ):
        self.nsjail_path = (
            nsjail_path if nsjail_path is not None else shutil.which("nsjail")
        )
        self.cgroup_v2_available = cgroup_v2_available
        self.platform = platform or get_platform()
        self.python_executable = pathlib.Path(
            python_executable or sys.executable
        ).absolute()
        self.python_prefix = pathlib.Path(python_prefix or sys.prefix).absolute()
        self.policy: PluginWorkerPolicy | None = None
        self.runtime_profile: Literal["oss_dev", "shared"] | None = None

    def configure(
        self,
        policy: PluginWorkerPolicy,
        runtime_profile: Literal["oss_dev", "shared"],
    ) -> None:
        if self.policy is not None and self.policy != policy:
            raise ValueError("Plugin worker launcher policy cannot be changed")
        if self.runtime_profile is not None and self.runtime_profile != runtime_profile:
            raise ValueError("Plugin worker launcher profile cannot be changed")

        if runtime_profile == "shared":
            if self.platform != "linux":
                raise RuntimeError("Shared plugin workers require Linux nsjail")
            if not self.nsjail_path:
                raise RuntimeError("Shared plugin workers require nsjail")
            self._validate_python_runtime()
            if self.cgroup_v2_available is None:
                self.cgroup_v2_available = self._detect_cgroup_v2_delegation()
        elif self.cgroup_v2_available is None:
            self.cgroup_v2_available = False
        if policy.require_hard_limits and not self.cgroup_v2_available:
            raise RuntimeError(
                "Plugin worker hard limits require delegated cgroup v2 controllers"
            )

        self.policy = policy
        self.runtime_profile = runtime_profile

    def create_controller(
        self,
        launch_spec: PluginWorkerLaunchSpec,
    ) -> stdio_client_controller.StdioClientController:
        policy, profile = self._require_configuration()
        if profile == "shared":
            return stdio_client_controller.StdioClientController(
                command=str(self.nsjail_path),
                args=self.build_nsjail_args(launch_spec),
                env={},
                working_dir="/",
            )

        # OSS development keeps the historical direct-process behavior and
        # artifact .env loading. Only the one-use registration capability and
        # explicit profile cross this process boundary.
        del policy
        return stdio_client_controller.StdioClientController(
            command=sys.executable,
            args=[
                "-m",
                "langbot_plugin.cli.__init__",
                "run",
                "-s",
                "--prod",
            ],
            env={
                PLUGIN_REGISTRATION_CAPABILITY_ENV: (
                    launch_spec.registration_capability
                ),
                PLUGIN_RUNTIME_PROFILE_ENV: "oss_dev",
            },
            working_dir=str(launch_spec.artifact.code_path),
        )

    def build_nsjail_args(self, launch_spec: PluginWorkerLaunchSpec) -> list[str]:
        policy, profile = self._require_configuration()
        if profile != "shared" or not self.nsjail_path:
            raise RuntimeError("nsjail arguments require the shared Runtime profile")

        runtime_prefix_mount = self._python_prefix_mount()
        self._ensure_jail_mount_targets(
            launch_spec.paths.jail_root_path,
            extra_targets=(runtime_prefix_mount,) if runtime_prefix_mount else (),
        )
        args = ["--mode", "o", "--chroot", str(launch_spec.paths.jail_root_path)]
        args.append("--disable_clone_newnet")

        for path in _READONLY_SYSTEM_MOUNTS:
            if os.path.exists(path) and not os.path.islink(path):
                args.extend(["--bindmount_ro", f"{path}:{path}"])
        for path in _READONLY_ETC_FILES:
            if os.path.exists(path) and not os.path.islink(path):
                args.extend(["--bindmount_ro", f"{path}:{path}"])
        if runtime_prefix_mount is not None:
            args.extend(
                [
                    "--bindmount_ro",
                    f"{runtime_prefix_mount}:{runtime_prefix_mount}",
                ]
            )

        args.extend(
            [
                "--bindmount_ro",
                f"{launch_spec.artifact.code_path}:/plugin",
                "--bindmount",
                f"{launch_spec.paths.home_path}:/home",
                "--bindmount",
                f"{launch_spec.paths.tmp_path}:/tmp",
                "--bindmount",
                f"{launch_spec.paths.data_path}:/data",
                "--mount",
                "none:/proc:proc:rw",
                "--mount",
                "none:/dev:tmpfs:rw",
            ]
        )
        for device in _DEV_NODES:
            if os.path.exists(device):
                args.extend(["--bindmount", f"{device}:{device}"])

        args.extend(
            [
                "--cwd",
                "/plugin",
                "--env",
                "HOME=/home",
                "--env",
                "TMPDIR=/tmp",
                "--env",
                "PYTHONUNBUFFERED=1",
                "--env",
                f"{PLUGIN_RUNTIME_PROFILE_ENV}=shared",
                "--env",
                f"{PLUGIN_REGISTRATION_CAPABILITY_ENV}={launch_spec.registration_capability}",
            ]
        )

        if self.cgroup_v2_available:
            args.extend(
                [
                    "--use_cgroupv2",
                    "--cgroup_mem_max",
                    str(policy.max_memory_mb * 1024 * 1024),
                    "--cgroup_pids_max",
                    str(policy.max_pids),
                    "--cgroup_cpu_ms_per_sec",
                    str(max(1, int(policy.max_cpus * 1000))),
                ]
            )
        args.extend(
            [
                "--rlimit_as",
                "hard",
                "--rlimit_nproc",
                str(policy.max_pids),
                "--rlimit_nofile",
                str(policy.max_open_files),
                "--rlimit_fsize",
                str(policy.max_file_size_mb),
                "--really_quiet",
                "--",
                str(self.python_executable),
                "-m",
                "langbot_plugin.cli.__init__",
                "run",
                "-s",
                "--prod",
            ]
        )
        return args

    def _require_configuration(
        self,
    ) -> tuple[PluginWorkerPolicy, Literal["oss_dev", "shared"]]:
        if self.policy is None or self.runtime_profile is None:
            raise RuntimeError("Plugin worker launcher is not configured")
        return self.policy, self.runtime_profile

    @staticmethod
    def _ensure_jail_mount_targets(
        root_path: pathlib.Path,
        *,
        extra_targets: tuple[pathlib.Path, ...] = (),
    ) -> None:
        targets = {
            "/plugin",
            "/home",
            "/tmp",
            "/data",
            "/proc",
            "/dev",
            *_READONLY_SYSTEM_MOUNTS,
            *_READONLY_ETC_FILES,
            *(str(path) for path in extra_targets),
        }
        for target_path in targets:
            host_target = root_path / target_path.lstrip("/")
            if os.path.islink(target_path):
                host_target.parent.mkdir(parents=True, exist_ok=True)
                link_value = os.readlink(target_path)
                if os.path.lexists(host_target):
                    if (
                        host_target.is_symlink()
                        and os.readlink(host_target) == link_value
                    ):
                        continue
                    if host_target.is_dir():
                        host_target.rmdir()
                    else:
                        host_target.unlink()
                host_target.symlink_to(link_value)
            elif os.path.isfile(target_path):
                host_target.parent.mkdir(parents=True, exist_ok=True)
                host_target.touch(exist_ok=True)
            else:
                host_target.mkdir(parents=True, exist_ok=True)

    def _validate_python_runtime(self) -> None:
        if (
            not self.python_executable.is_absolute()
            or not self.python_prefix.is_absolute()
        ):
            raise RuntimeError("Shared plugin worker Python paths must be absolute")
        if not self.python_executable.exists():
            raise RuntimeError("Shared plugin worker Python executable does not exist")
        if not self.python_prefix.is_dir():
            raise RuntimeError("Shared plugin worker Python prefix does not exist")
        if self._path_covered_by_system_mount(self.python_executable):
            return
        try:
            self.python_executable.relative_to(self.python_prefix)
        except ValueError as exc:
            raise RuntimeError(
                "Shared plugin worker Python executable must be inside its mounted prefix"
            ) from exc

    def _python_prefix_mount(self) -> pathlib.Path | None:
        if self._path_covered_by_system_mount(self.python_prefix):
            return None
        return self.python_prefix

    @staticmethod
    def _path_covered_by_system_mount(path: pathlib.Path) -> bool:
        return any(
            path == pathlib.Path(root) or pathlib.Path(root) in path.parents
            for root in _READONLY_SYSTEM_MOUNTS
        )

    @staticmethod
    def _detect_cgroup_v2_delegation() -> bool:
        cgroup_root = pathlib.Path("/sys/fs/cgroup")
        controllers_path = cgroup_root / "cgroup.controllers"
        subtree_path = cgroup_root / "cgroup.subtree_control"
        try:
            available = set(controllers_path.read_text().split())
            enabled = set(subtree_path.read_text().split())
        except OSError:
            return False
        required = {"cpu", "memory", "pids"}
        if not required.issubset(available):
            return False

        for controller in ("memory", "pids", "cpu"):
            try:
                subtree_path.write_text(f"+{controller}")
            except OSError:
                return False
            if controller not in enabled:
                try:
                    subtree_path.write_text(f"-{controller}")
                except OSError:
                    return False
        return True
