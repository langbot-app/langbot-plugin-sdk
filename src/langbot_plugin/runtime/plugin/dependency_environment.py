from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import pathlib
import re
import shutil
import stat
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from langbot_plugin.runtime.plugin.artifact import PluginArtifact


_ENVIRONMENT_SCHEMA_VERSION = 1
_READY_MARKER = ".ready.json"
_MAX_REQUIREMENTS_BYTES = 1024 * 1024
_MAX_REQUIREMENT_COUNT = 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DependencyEnvironmentPreparationError(RuntimeError):
    """A stable, user-safe failure raised before a shared worker is launched."""


@dataclass(frozen=True, slots=True)
class PluginDependencyEnvironment:
    """One immutable dependency tree shared by workers for the same environment."""

    digest: str
    artifact_digest: str
    requirements_digest: str
    runtime_fingerprint: str
    root_path: pathlib.Path
    site_packages_path: pathlib.Path


@dataclass(frozen=True, slots=True)
class DependencyEnvironmentStaging:
    """Runtime-owned writable paths visible only to the preparation sandbox."""

    root_path: pathlib.Path
    site_packages_path: pathlib.Path
    scratch_path: pathlib.Path
    jail_root_path: pathlib.Path
    tmp_path: pathlib.Path


DependencyInstaller = Callable[
    [DependencyEnvironmentStaging, Sequence[str]], Awaitable[None]
]


class PluginDependencyEnvironmentStore:
    """Atomically prepare and publish immutable per-artifact dependency trees."""

    def __init__(self, base_path: str | os.PathLike = "data/plugin-runtime"):
        self.base_path = pathlib.Path(base_path)
        self.environments_path = self.base_path / "environments" / "sha256"
        self._prepare_locks: dict[str, asyncio.Lock] = {}

    async def prepare(
        self,
        artifact: PluginArtifact,
        *,
        runtime_fingerprint: str,
        installer: DependencyInstaller,
    ) -> PluginDependencyEnvironment:
        requirements, requirements_digest = self._read_requirements(artifact)
        digest = self._environment_digest(
            artifact.digest,
            requirements_digest,
            runtime_fingerprint,
        )
        expected = self._metadata(
            digest=digest,
            artifact_digest=artifact.digest,
            requirements_digest=requirements_digest,
            runtime_fingerprint=runtime_fingerprint,
        )

        ready = self.get_ready(digest, expected=expected)
        if ready is not None:
            return ready

        lock = self._prepare_locks.setdefault(digest, asyncio.Lock())
        async with lock:
            ready = self.get_ready(digest, expected=expected)
            if ready is not None:
                return ready
            return await self._prepare_locked(
                artifact,
                digest=digest,
                expected=expected,
                requirements=requirements,
                installer=installer,
            )

    def get_ready(
        self,
        digest: str,
        *,
        expected: dict[str, object] | None = None,
    ) -> PluginDependencyEnvironment | None:
        if _SHA256_PATTERN.fullmatch(str(digest or "")) is None:
            return None
        root_path = self.environments_path / digest
        marker_path = root_path / _READY_MARKER
        site_packages_path = root_path / "site-packages"
        try:
            metadata = json.loads(marker_path.read_text(encoding="utf-8"))
            root_mode = stat.S_IMODE(root_path.stat().st_mode)
            site_mode = stat.S_IMODE(site_packages_path.stat().st_mode)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(metadata, dict) or metadata.get("digest") != digest:
            return None
        if expected is not None and metadata != expected:
            return None
        if not site_packages_path.is_dir():
            return None
        if root_mode & 0o222 or site_mode & 0o222:
            return None
        try:
            return PluginDependencyEnvironment(
                digest=digest,
                artifact_digest=str(metadata["artifact_digest"]),
                requirements_digest=str(metadata["requirements_digest"]),
                runtime_fingerprint=str(metadata["runtime_fingerprint"]),
                root_path=root_path,
                site_packages_path=site_packages_path,
            )
        except KeyError:
            return None

    async def _prepare_locked(
        self,
        artifact: PluginArtifact,
        *,
        digest: str,
        expected: dict[str, object],
        requirements: Sequence[str],
        installer: DependencyInstaller,
    ) -> PluginDependencyEnvironment:
        self.environments_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary_root = pathlib.Path(
            tempfile.mkdtemp(prefix=f".{digest}.", dir=self.environments_path)
        )
        staging = DependencyEnvironmentStaging(
            root_path=temporary_root,
            site_packages_path=temporary_root / "site-packages",
            scratch_path=temporary_root / ".scratch",
            jail_root_path=temporary_root / ".scratch" / "root",
            tmp_path=temporary_root / ".scratch" / "tmp",
        )
        staging.site_packages_path.mkdir(mode=0o700)
        staging.jail_root_path.mkdir(parents=True, mode=0o700)
        staging.tmp_path.mkdir(mode=0o700)

        try:
            await installer(staging, requirements)
            # Validate structure before reading distribution metadata: a build
            # backend is untrusted and could otherwise make the Runtime follow
            # a link outside the staging tree while verifying its output.
            self._validate_tree_entries(staging.site_packages_path)
            self._validate_installed_requirements(
                staging.site_packages_path,
                requirements,
            )
            shutil.rmtree(staging.scratch_path)
            self._make_tree_read_only(staging.site_packages_path)
            self._write_marker(temporary_root / _READY_MARKER, expected)
            temporary_root.chmod(0o555)

            target_root = self.environments_path / digest
            try:
                os.rename(temporary_root, target_root)
            except OSError:
                # Another Runtime process may have completed the exact same
                # environment while this process was preparing its staging tree.
                ready = self.get_ready(digest, expected=expected)
                if ready is None:
                    raise
                shutil.rmtree(temporary_root, ignore_errors=True)
                return ready
            self._fsync_directory(self.environments_path)

            ready = self.get_ready(digest, expected=expected)
            if ready is None:  # pragma: no cover - publication invariant
                raise RuntimeError("Dependency environment publication failed")
            return ready
        except BaseException:
            if temporary_root.exists():
                shutil.rmtree(temporary_root, ignore_errors=True)
            raise

    @staticmethod
    def _read_requirements(
        artifact: PluginArtifact,
    ) -> tuple[tuple[str, ...], str]:
        requirements_path = artifact.code_path / "requirements.txt"
        try:
            content = requirements_path.read_bytes()
        except FileNotFoundError:
            content = b""
        except OSError as exc:
            raise DependencyEnvironmentPreparationError(
                "Plugin dependency declarations are unavailable"
            ) from exc
        if len(content) > _MAX_REQUIREMENTS_BYTES:
            raise DependencyEnvironmentPreparationError(
                "Plugin requirements.txt exceeds the shared Runtime limit"
            )
        requirements_digest = hashlib.sha256(content).hexdigest()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DependencyEnvironmentPreparationError(
                "Plugin requirements.txt must be UTF-8"
            ) from exc

        requirements: list[str] = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-"):
                raise DependencyEnvironmentPreparationError(
                    "Shared Runtime requirements.txt cannot contain pip options "
                    f"(line {line_number})"
                )
            try:
                requirement = Requirement(line)
            except InvalidRequirement as exc:
                raise DependencyEnvironmentPreparationError(
                    "Shared Runtime requirements.txt contains an invalid requirement "
                    f"(line {line_number})"
                ) from exc
            requirements.append(str(requirement))
            if len(requirements) > _MAX_REQUIREMENT_COUNT:
                raise DependencyEnvironmentPreparationError(
                    "Plugin requirements.txt contains too many requirements"
                )
        return tuple(requirements), requirements_digest

    @staticmethod
    def _validate_installed_requirements(
        site_packages_path: pathlib.Path,
        requirements: Sequence[str],
    ) -> None:
        distributions: dict[str, list[importlib.metadata.Distribution]] = {}
        for distribution in importlib.metadata.distributions(
            path=[str(site_packages_path)]
        ):
            name = distribution.metadata.get("Name")
            if name:
                distributions.setdefault(canonicalize_name(name), []).append(
                    distribution
                )

        unsatisfied: list[str] = []
        for value in requirements:
            requirement = Requirement(value)
            if requirement.marker is not None and not requirement.marker.evaluate():
                continue
            matches = distributions.get(canonicalize_name(requirement.name), [])
            if requirement.url:
                if not matches:
                    unsatisfied.append(value)
                continue
            if not any(
                not requirement.specifier
                or distribution.version in requirement.specifier
                for distribution in matches
            ):
                unsatisfied.append(value)
        if unsatisfied:
            raise DependencyEnvironmentPreparationError(
                "Prepared dependency environment has "
                f"{len(unsatisfied)} unsatisfied requirement(s)"
            )

    @staticmethod
    def _validate_tree_entries(root_path: pathlib.Path) -> None:
        for path in root_path.rglob("*"):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise DependencyEnvironmentPreparationError(
                    "Prepared dependency environment contains a symbolic link"
                )
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise DependencyEnvironmentPreparationError(
                    "Prepared dependency environment contains a special file"
                )

    @staticmethod
    def _make_tree_read_only(root_path: pathlib.Path) -> None:
        for path in root_path.rglob("*"):
            mode = stat.S_IMODE(path.stat().st_mode)
            if path.is_dir():
                path.chmod((mode & ~0o222) | 0o555)
            else:
                path.chmod((mode & ~0o222) | 0o444)
        root_path.chmod(0o555)

    @staticmethod
    def _write_marker(path: pathlib.Path, metadata: dict[str, object]) -> None:
        with path.open("w", encoding="utf-8") as marker:
            json.dump(metadata, marker, sort_keys=True, separators=(",", ":"))
            marker.write("\n")
            marker.flush()
            os.fsync(marker.fileno())
        path.chmod(0o444)

    @staticmethod
    def _fsync_directory(path: pathlib.Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _environment_digest(
        artifact_digest: str,
        requirements_digest: str,
        runtime_fingerprint: str,
    ) -> str:
        payload = {
            "artifact_digest": artifact_digest,
            "requirements_digest": requirements_digest,
            "runtime_fingerprint": runtime_fingerprint,
            "schema_version": _ENVIRONMENT_SCHEMA_VERSION,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _metadata(
        *,
        digest: str,
        artifact_digest: str,
        requirements_digest: str,
        runtime_fingerprint: str,
    ) -> dict[str, object]:
        return {
            "artifact_digest": artifact_digest,
            "digest": digest,
            "requirements_digest": requirements_digest,
            "runtime_fingerprint": runtime_fingerprint,
            "schema_version": _ENVIRONMENT_SCHEMA_VERSION,
        }
