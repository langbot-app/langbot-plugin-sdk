from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass

import yaml

from langbot_plugin.entities.io.context import InstallationBinding


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERIFIED_MARKER = ".verified-sha256"
_MAX_ARTIFACT_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PluginArtifact:
    digest: str
    root_path: pathlib.Path
    code_path: pathlib.Path
    plugin_author: str
    plugin_name: str
    plugin_version: str


@dataclass(frozen=True, slots=True)
class PluginInstallationPaths:
    root_path: pathlib.Path
    home_path: pathlib.Path
    tmp_path: pathlib.Path
    data_path: pathlib.Path
    jail_root_path: pathlib.Path


class PluginArtifactStore:
    """Verified read-only artifacts plus installation-private writable paths."""

    def __init__(self, base_path: str | os.PathLike = "data/plugin-runtime"):
        self.base_path = pathlib.Path(base_path)
        self.artifacts_path = self.base_path / "artifacts" / "sha256"
        self.installations_path = self.base_path / "installations"

    def install_package(self, package: bytes, expected_digest: str) -> PluginArtifact:
        digest = self._validate_digest(expected_digest)
        actual_digest = hashlib.sha256(package).hexdigest()
        if actual_digest != digest:
            raise ValueError(
                f"Plugin artifact digest mismatch: expected {digest}, got {actual_digest}"
            )

        existing = self.get_verified(digest)
        if existing is not None:
            return existing

        self.artifacts_path.mkdir(parents=True, exist_ok=True)
        temporary_root = pathlib.Path(
            tempfile.mkdtemp(prefix=f".{digest}.", dir=self.artifacts_path)
        )
        code_path = temporary_root / "code"
        code_path.mkdir()
        try:
            self._extract_verified_zip(package, code_path)
            plugin_author, plugin_name, plugin_version = self._read_manifest(code_path)
            self._make_tree_read_only(code_path)
            (temporary_root / _VERIFIED_MARKER).write_text(digest, encoding="ascii")

            target_root = self.artifacts_path / digest
            try:
                os.replace(temporary_root, target_root)
            except OSError:
                # Another apply may have published the same verified digest.
                if self.get_verified(digest) is None:
                    raise
                shutil.rmtree(temporary_root, ignore_errors=True)

            artifact = self.get_verified(digest)
            if artifact is None:  # pragma: no cover - publication invariant
                raise RuntimeError("Verified plugin artifact publication failed")
            if (
                artifact.plugin_author != plugin_author
                or artifact.plugin_name != plugin_name
                or artifact.plugin_version != plugin_version
            ):
                raise RuntimeError("Published plugin artifact manifest changed")
            return artifact
        except Exception:
            if temporary_root.exists():
                shutil.rmtree(temporary_root, ignore_errors=True)
            raise

    def require_verified(self, digest: str) -> PluginArtifact:
        artifact = self.get_verified(digest)
        if artifact is None:
            raise ValueError(f"Verified plugin artifact is unavailable: {digest}")
        return artifact

    def get_verified(self, digest: str) -> PluginArtifact | None:
        digest = self._validate_digest(digest)
        root_path = self.artifacts_path / digest
        code_path = root_path / "code"
        marker_path = root_path / _VERIFIED_MARKER
        try:
            marker = marker_path.read_text(encoding="ascii").strip()
        except OSError:
            return None
        if marker != digest or not code_path.is_dir():
            return None
        plugin_author, plugin_name, plugin_version = self._read_manifest(code_path)
        return PluginArtifact(
            digest=digest,
            root_path=root_path,
            code_path=code_path,
            plugin_author=plugin_author,
            plugin_name=plugin_name,
            plugin_version=plugin_version,
        )

    def ensure_installation_paths(
        self,
        binding: InstallationBinding,
    ) -> PluginInstallationPaths:
        installation_uuid = self._safe_component(
            binding.installation_uuid,
            "installation_uuid",
        )
        root_path = self.installations_path / installation_uuid
        home_path = root_path / "home"
        tmp_path = root_path / "tmp"
        data_path = root_path / "data"
        jail_root_path = root_path / "root"
        for path in (home_path, tmp_path, data_path, jail_root_path):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        return PluginInstallationPaths(
            root_path=root_path,
            home_path=home_path,
            tmp_path=tmp_path,
            data_path=data_path,
            jail_root_path=jail_root_path,
        )

    @staticmethod
    def _validate_digest(value: str) -> str:
        digest = str(value or "").strip()
        if _SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError("artifact digest must be lowercase SHA-256 hex")
        return digest

    @staticmethod
    def _safe_component(value: str, field_name: str) -> str:
        component = str(value or "").strip()
        if _SAFE_COMPONENT_PATTERN.fullmatch(component) is None:
            raise ValueError(f"{field_name} is not safe for a private path")
        return component

    @staticmethod
    def _extract_verified_zip(package: bytes, destination: pathlib.Path) -> None:
        from io import BytesIO

        total_size = 0
        with zipfile.ZipFile(BytesIO(package), "r") as archive:
            for info in archive.infolist():
                member = pathlib.PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError("Plugin artifact contains an unsafe path")
                unix_mode = info.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise ValueError("Plugin artifact must not contain symbolic links")
                total_size += info.file_size
                if total_size > _MAX_ARTIFACT_UNCOMPRESSED_BYTES:
                    raise ValueError("Plugin artifact exceeds the extraction limit")

                target = destination.joinpath(*member.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)

    @staticmethod
    def _read_manifest(code_path: pathlib.Path) -> tuple[str, str, str]:
        manifest_path = code_path / "manifest.yaml"
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError("Plugin artifact manifest.yaml is unavailable") from exc
        if not isinstance(manifest, dict) or manifest.get("kind") != "Plugin":
            raise ValueError("Plugin artifact manifest must have kind=Plugin")
        metadata = manifest.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("Plugin artifact manifest metadata is missing")
        author = str(metadata.get("author") or "").strip()
        name = str(metadata.get("name") or "").strip()
        version = str(metadata.get("version") or "").strip()
        if not author or not name or not version:
            raise ValueError("Plugin artifact manifest identity is incomplete")
        return author, name, version

    @staticmethod
    def _make_tree_read_only(root_path: pathlib.Path) -> None:
        for path in root_path.rglob("*"):
            if path.is_dir():
                path.chmod(0o555)
            else:
                path.chmod(0o444)
        root_path.chmod(0o555)
