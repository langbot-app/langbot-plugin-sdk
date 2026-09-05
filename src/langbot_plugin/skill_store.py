from __future__ import annotations

import collections
import datetime as dt
import hashlib
import io
import mimetypes
import os
import posixpath
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import yaml

from .workspace import workspace_namespace


_FRONTMATTER_FIELDS = (
    "name",
    "display_name",
    "description",
)

_PUBLIC_SKILL_FIELDS = (
    "name",
    "display_name",
    "description",
    "instructions",
    "package_root",
    "entry_file",
    "python_project",
    "created_at",
    "updated_at",
)

# Skill uploads are untrusted. These fixed store-owned caps apply to both
# preview and installation and are deliberately not configurable per tenant.
_MAX_ZIP_COMPRESSED_BYTES = 20 * 1024 * 1024
_MAX_ZIP_ENTRIES = 512
_MAX_ZIP_ENTRY_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
_MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_ZIP_COMPRESSION_RATIO = 100.0
_ZIP_COPY_CHUNK_BYTES = 64 * 1024
_MAX_SKILL_TEXT_BYTES = 1024 * 1024
_MAX_DISCOVERED_SKILLS = 1_000
_MAX_SKILL_SCAN_ENTRIES = 10_000
_MAX_SKILL_LIST_ENTRIES = 1_000
_MAX_SKILL_DIRECTORY_ENTRIES = 10_000
_MAX_SKILL_LIST_TOTAL_TEXT_BYTES = 16 * 1024 * 1024
_MAX_REVISION_FILES = 2_048
_MAX_REVISION_BYTES = 64 * 1024 * 1024
_REVISION_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


class SkillRevisionMismatchError(ValueError):
    """Raised when a caller reads a package other than the activated revision."""


def skill_namespace(instance_uuid: str, workspace_uuid: str) -> str:
    """Return the durable Skill namespace for one instance and Workspace."""

    return workspace_namespace(instance_uuid, workspace_uuid)


def _read_utf8_text_limited(path: str, *, subject: str) -> str:
    if os.path.getsize(path) > _MAX_SKILL_TEXT_BYTES:
        raise ValueError(f"{subject} exceeds the {_MAX_SKILL_TEXT_BYTES}-byte limit")
    with open(path, "rb") as file:
        content = file.read(_MAX_SKILL_TEXT_BYTES + 1)
    if len(content) > _MAX_SKILL_TEXT_BYTES:
        raise ValueError(f"{subject} exceeds the {_MAX_SKILL_TEXT_BYTES}-byte limit")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{subject} is not valid UTF-8 text") from exc


def parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, content

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            metadata_text = "".join(lines[1:index])
            instructions = "".join(lines[index + 1 :]).lstrip("\n")
            metadata = yaml.safe_load(metadata_text) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            return metadata, instructions

    return {}, content


def build_skill_md(metadata: dict, instructions: str) -> str:
    frontmatter = {}
    for key in _FRONTMATTER_FIELDS:
        value = metadata.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        frontmatter[key] = value

    if not frontmatter:
        return instructions

    frontmatter_text = yaml.dump(
        frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False
    ).strip()
    return f"---\n{frontmatter_text}\n---\n\n{instructions}"


class SkillStore:
    """Filesystem-backed Skill package storage independent from execution."""

    def __init__(
        self,
        root: str | os.PathLike[str] = "./data/skills",
        *,
        namespace: str | None = None,
    ):
        root_path = Path(root).expanduser()
        if not root_path.is_absolute():
            root_path = Path.cwd() / root_path
        self._base_root = root_path.resolve()
        self._namespace = namespace

    def scoped(self, namespace: str) -> SkillStore:
        """Return an immutable Workspace view over the configured skill store."""

        normalized = str(namespace or "").strip()
        if (
            not normalized
            or "/" in normalized
            or "\\" in normalized
            or normalized in {".", ".."}
        ):
            raise ValueError("Invalid Skill store namespace")
        return SkillStore(self._base_root, namespace=normalized)

    @property
    def root(self) -> str:
        resolved_root = self._base_root
        if self._namespace is not None:
            resolved_root = resolved_root / "tenants" / self._namespace
        return str(resolved_root)

    def list_skills(self) -> list[dict]:
        os.makedirs(self.root, exist_ok=True)
        skills: list[dict] = []
        retained_text_bytes = 0
        for package_root, entry_file in self._discover_skill_directories(
            self.root, max_depth=6
        ):
            try:
                skill = self._load_skill_package(package_root, entry_file)
            except Exception:
                continue
            retained_text_bytes += sum(
                len(value.encode("utf-8"))
                for value in skill.values()
                if isinstance(value, str)
            )
            if retained_text_bytes > _MAX_SKILL_LIST_TOTAL_TEXT_BYTES:
                raise ValueError("Skill listing exceeds the configured text limit")
            skills.append(skill)
        skills.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return [self._serialize_skill(skill) for skill in skills]

    def get_skill(self, skill_name: str) -> Optional[dict]:
        for skill in self.list_skills():
            if skill.get("name") == skill_name:
                return skill
        return None

    def get_skill_snapshot(self, skill_name: str) -> Optional[dict]:
        """Return one Skill together with its immutable package revision."""

        skill = self.get_skill(skill_name)
        if skill is None:
            return None
        result = dict(skill)
        result["revision"] = self._package_revision(result["package_root"])
        return result

    def resolve_skill_package_root(self, skill_name: str) -> str:
        """Return a trusted package root for a Runtime-owned sandbox mount.

        Only Workspace-scoped stores may resolve mounts. The result comes from
        the store's own discovery, is canonicalized back under that Workspace's
        root, and never incorporates a Core-supplied host path.
        """

        if self._namespace is None:
            raise ValueError("Skill sandbox mounts require a Workspace-scoped store")
        skill_name = self._validate_skill_name(skill_name)
        skill = self._require_skill(skill_name)
        package_root = self._require_scoped_path(
            str(skill.get("package_root") or ""), "skill package"
        )
        if not os.path.isdir(package_root):
            raise ValueError(f'Skill "{skill_name}" package directory is unavailable')
        return package_root

    def create_skill(self, data: dict) -> dict:
        name = self._validate_skill_name(data.get("name", ""))
        if self.get_skill(name):
            raise ValueError(f'Skill with name "{name}" already exists')

        package_root = self._normalize_package_root(data.get("package_root", ""))
        if self._namespace is not None and package_root:
            self._require_scoped_path(package_root, "package_root")
        managed_root = self._managed_skill_path(name)
        target_root = managed_root
        imported_skill_data: dict | None = None

        if package_root and self._managed_install_root_for_package(package_root):
            if not os.path.isdir(package_root):
                raise ValueError(f"Directory does not exist: {package_root}")
            target_root = package_root
            imported_skill_data = self._read_skill_package(target_root)
        elif package_root and package_root != managed_root:
            if not os.path.isdir(package_root):
                raise ValueError(f"Directory does not exist: {package_root}")
            if os.path.exists(managed_root):
                raise ValueError(f"Skill directory already exists: {managed_root}")
            os.makedirs(os.path.dirname(managed_root), exist_ok=True)
            shutil.copytree(package_root, managed_root)
            imported_skill_data = self._read_skill_package(managed_root)
        else:
            os.makedirs(managed_root, exist_ok=True)

        metadata = {
            "name": name,
            "display_name": self._resolve_create_field(
                data, "display_name", imported_skill_data, default=""
            ),
            "description": self._resolve_create_field(
                data, "description", imported_skill_data, default=""
            ),
        }
        instructions = self._resolve_create_field(
            data, "instructions", imported_skill_data, default=""
        )
        self._write_skill_md(target_root, metadata, instructions)

        created = self.get_skill(name)
        if not created:
            raise ValueError(f'Failed to create skill "{name}"')
        return created

    def update_skill(self, skill_name: str, data: dict) -> dict:
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f'Skill "{skill_name}" not found')

        requested_name = str(data.get("name", skill["name"]) or skill["name"]).strip()
        if requested_name != skill["name"]:
            raise ValueError("Renaming skills is not supported")

        requested_package_root = str(data.get("package_root", "") or "").strip()
        existing_package_root = self._normalize_package_root(skill["package_root"])
        if (
            requested_package_root
            and self._normalize_package_root(requested_package_root)
            != existing_package_root
        ):
            raise ValueError(
                "Updating package_root is not supported; recreate the skill to import a different package"
            )

        metadata = {
            "name": skill["name"],
            "display_name": data.get("display_name", skill.get("display_name", "")),
            "description": data.get("description", skill.get("description", "")),
        }
        instructions = str(
            data.get("instructions", skill.get("instructions", "")) or ""
        )
        self._write_skill_md(skill["package_root"], metadata, instructions)

        updated = self.get_skill(skill_name)
        if not updated:
            raise ValueError(f'Skill "{skill_name}" not found after update')
        return updated

    def delete_skill(self, skill_name: str) -> dict:
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f'Skill "{skill_name}" not found')

        package_root = self._normalize_package_root(skill["package_root"])
        managed_install_root = self._managed_install_root_for_package(package_root)
        if not managed_install_root:
            raise ValueError(
                "Only managed skills under the Skill store root can be deleted"
            )

        shutil.rmtree(managed_install_root, ignore_errors=True)
        return {"deleted": skill_name}

    def scan_directory(self, path: str) -> dict:
        if self._namespace is not None:
            path = self._require_scoped_path(path, "scan path")
        if not os.path.isdir(path):
            raise ValueError(f"Directory does not exist: {path}")

        discovered = self._discover_skill_directories(path, max_depth=2)
        if not discovered:
            raise ValueError(
                f"No SKILL.md found in {path} or its subdirectories (max depth: 2)"
            )
        if len(discovered) > 1:
            candidates = ", ".join(found_path for found_path, _entry in discovered)
            raise ValueError(
                f"Multiple skill directories found in {path}. Please choose a more specific path: {candidates}"
            )

        package_root, entry_file = discovered[0]
        return self._load_skill_package(package_root, entry_file)

    def scan_import_directory(self, path: str, *, source_root: str) -> dict:
        """Scan a trusted import source without granting arbitrary host access."""

        source = self._require_path_under(path, source_root, "scan path")
        self._require_safe_import_tree(source)
        return SkillStore(self.root).scan_directory(source)

    def import_skill_directory(
        self,
        path: str,
        data: dict,
        *,
        source_root: str,
    ) -> dict:
        """Copy a package from a fenced source tree into this managed store."""

        source = self._require_path_under(path, source_root, "import path")
        self._require_safe_import_tree(source)
        payload = dict(data)
        payload["package_root"] = source
        return SkillStore(self.root).create_skill(payload)

    def _require_scoped_path(self, path: str, label: str) -> str:
        """Keep host-path operations inside this Workspace's skill root.

        A scoped SkillStore may be shared by mutually untrusted Workspaces. Host
        paths supplied over RPC are therefore routing input, not authority.
        ``realpath`` also prevents a symlink inside one tenant root from being
        used to import or scan another tenant's files.
        """

        candidate = self._normalize_package_root(path)
        scoped_root = self._normalize_package_root(self.root)
        if not candidate or (
            candidate != scoped_root
            and not candidate.startswith(f"{scoped_root}{os.sep}")
        ):
            raise ValueError(f"{label} must stay within the Workspace skill root")
        return candidate

    def list_skill_files(
        self,
        skill_name: str,
        path: str = ".",
        include_hidden: bool = False,
        max_entries: int = 200,
    ) -> dict:
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or max_entries <= 0
        ):
            raise ValueError("max_entries must be a positive integer")
        max_entries = min(max_entries, _MAX_SKILL_LIST_ENTRIES)
        skill = self._require_skill(skill_name)
        target_dir, relative_path = self._resolve_skill_path(
            skill, path, expect_directory=True
        )
        with os.scandir(target_dir) as iterator:
            directory_entries = []
            for entry in iterator:
                if len(directory_entries) >= _MAX_SKILL_DIRECTORY_ENTRIES:
                    raise ValueError(
                        "Skill directory exceeds the configured entry limit"
                    )
                directory_entries.append(entry)
        directory_entries.sort(key=lambda item: item.name)
        visible_entries = [
            entry
            for entry in directory_entries
            if include_hidden or not entry.name.startswith(".")
        ]
        entries: list[dict] = []
        for entry in visible_entries[:max_entries]:
            entry_rel_path = (
                entry.name
                if relative_path in ("", ".")
                else os.path.join(relative_path, entry.name)
            )
            is_dir = entry.is_dir()
            entries.append(
                {
                    "path": entry_rel_path.replace(os.sep, "/"),
                    "name": entry.name,
                    "is_dir": is_dir,
                    "size": None if is_dir else entry.stat().st_size,
                }
            )

        return {
            "skill": {"name": skill["name"]},
            "base_path": "."
            if relative_path in ("", ".")
            else relative_path.replace(os.sep, "/"),
            "entries": entries,
            "truncated": len(visible_entries) > max_entries,
        }

    def read_skill_file(self, skill_name: str, path: str) -> dict:
        skill = self._require_skill(skill_name)
        target_path, relative_path = self._resolve_skill_path(
            skill, path, expect_directory=False
        )
        if not os.path.isfile(target_path):
            raise ValueError(f"Skill file not found: {relative_path}")

        content = _read_utf8_text_limited(
            target_path,
            subject=f"Skill file {relative_path}",
        )

        return {
            "skill": {"name": skill["name"]},
            "path": relative_path.replace(os.sep, "/"),
            "content": content,
        }

    def list_skill_resources(
        self,
        skill_name: str,
        path: str = ".",
        include_hidden: bool = False,
        max_entries: int = 200,
        *,
        expected_revision: str | None = None,
    ) -> dict:
        """List read-only package resources pinned to one Skill revision."""

        skill = self._require_skill(skill_name)
        revision = self._require_revision(skill, expected_revision)
        result = self.list_skill_files(
            skill_name,
            path,
            include_hidden,
            max_entries,
        )
        self._require_revision(skill, revision)
        result["revision"] = revision
        for entry in result.get("entries", []):
            if not entry.get("is_dir"):
                entry["mime_type"] = (
                    mimetypes.guess_type(str(entry.get("path", "")))[0] or "text/plain"
                )
        return result

    def read_skill_resource(
        self,
        skill_name: str,
        path: str,
        *,
        expected_revision: str | None = None,
    ) -> dict:
        """Read one UTF-8 package resource pinned to one Skill revision."""

        skill = self._require_skill(skill_name)
        revision = self._require_revision(skill, expected_revision)
        result = self.read_skill_file(skill_name, path)
        self._require_revision(skill, revision)
        result["revision"] = revision
        result["mime_type"] = mimetypes.guess_type(path)[0] or "text/plain"
        return result

    def write_skill_file(self, skill_name: str, path: str, content: str) -> dict:
        skill = self._require_skill(skill_name)
        target_path, relative_path = self._resolve_skill_path(
            skill, path, expect_directory=False
        )
        encoded_content = content.encode("utf-8")
        if len(encoded_content) > _MAX_SKILL_TEXT_BYTES:
            raise ValueError(
                f"Skill file {relative_path} exceeds the "
                f"{_MAX_SKILL_TEXT_BYTES}-byte limit"
            )
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "skill": {"name": skill["name"]},
            "path": relative_path.replace(os.sep, "/"),
            "bytes_written": len(encoded_content),
        }

    def preview_zip_upload(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        source_subdir: str = "",
        target_suffix: str = "upload",
    ) -> list[dict]:
        if not file_bytes:
            raise ValueError("Uploaded file is empty")
        self._validate_zip_upload_size(file_bytes)

        tmp_dir = tempfile.mkdtemp(prefix="langbot_skill_preview_")
        try:
            skill_root = self._extract_uploaded_skill_to_temp(file_bytes, tmp_dir)
            skill_root = self._resolve_source_subdir_root(skill_root, source_subdir)
            return self._preview_skill_candidates(
                skill_root,
                base_target_name=self._uploaded_skill_target_stem(filename),
                suffix=target_suffix,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def install_zip_upload(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        source_paths: list[str] | None = None,
        source_path: str = "",
        source_subdir: str = "",
        target_suffix: str = "upload",
    ) -> list[dict]:
        if not file_bytes:
            raise ValueError("Uploaded file is empty")
        self._validate_zip_upload_size(file_bytes)

        tmp_dir = tempfile.mkdtemp(prefix="langbot_skill_upload_")
        try:
            skill_root = self._extract_uploaded_skill_to_temp(file_bytes, tmp_dir)
            skill_root = self._resolve_source_subdir_root(skill_root, source_subdir)
            previews = self._preview_skill_candidates(
                skill_root,
                base_target_name=self._uploaded_skill_target_stem(filename),
                suffix=target_suffix,
            )
            selected_previews = self._select_preview_candidates(
                previews,
                {"source_paths": source_paths or [], "source_path": source_path},
            )
            scanned = self._install_preview_candidates(skill_root, selected_previews)
            return [
                self.get_skill(skill["name"]) or self._serialize_skill(skill)
                for skill in scanned
            ]
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _require_skill(self, skill_name: str) -> dict:
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f'Skill "{skill_name}" not found')
        return skill

    @staticmethod
    def _require_path_under(path: str, root: str, label: str) -> str:
        raw_candidate = os.path.abspath(str(path or "").strip())
        candidate = os.path.realpath(raw_candidate)
        trusted_root = os.path.realpath(os.path.abspath(str(root or "").strip()))
        if (
            not path
            or not root
            or (
                candidate != trusted_root
                and not candidate.startswith(f"{trusted_root}{os.sep}")
            )
        ):
            raise ValueError(f"{label} must stay within the trusted source root")
        if not os.path.isdir(candidate):
            raise ValueError(f"Directory does not exist: {path}")
        if os.path.islink(raw_candidate):
            raise ValueError(f"{label} cannot be a symbolic link")
        return candidate

    @staticmethod
    def _require_safe_import_tree(root: str) -> None:
        scanned_entries = 0
        for current_root, dir_names, file_names in os.walk(root, followlinks=False):
            for name in (*dir_names, *file_names):
                scanned_entries += 1
                if scanned_entries > _MAX_SKILL_SCAN_ENTRIES:
                    raise ValueError("Skill import exceeded the configured entry limit")
                path = os.path.join(current_root, name)
                stat_result = os.lstat(path)
                if stat.S_ISLNK(stat_result.st_mode):
                    raise ValueError("Skill imports cannot contain symbolic links")
                if name in file_names and not stat.S_ISREG(stat_result.st_mode):
                    raise ValueError("Skill imports can contain regular files only")

    @staticmethod
    def _package_revision(package_root: str) -> str:
        root = os.path.realpath(str(package_root or "").strip())
        if not root or not os.path.isdir(root):
            raise ValueError("Skill package directory is unavailable")

        digest = hashlib.sha256()
        file_count = 0
        total_bytes = 0
        for current_root, dir_names, file_names in os.walk(root, followlinks=False):
            dir_names[:] = [
                name for name in dir_names if name not in _REVISION_SKIP_DIRS
            ]
            dir_names.sort()
            file_names.sort()
            for directory_name in tuple(dir_names):
                if os.path.islink(os.path.join(current_root, directory_name)):
                    raise ValueError("Skill packages cannot contain symbolic links")
            for file_name in file_names:
                path = os.path.join(current_root, file_name)
                if os.path.islink(path):
                    raise ValueError("Skill packages cannot contain symbolic links")
                stat_result = os.stat(path, follow_symlinks=False)
                if not stat.S_ISREG(stat_result.st_mode):
                    raise ValueError("Skill packages can contain regular files only")
                file_count += 1
                if file_count > _MAX_REVISION_FILES:
                    raise ValueError("Skill package contains too many files")
                total_bytes += stat_result.st_size
                if total_bytes > _MAX_REVISION_BYTES:
                    raise ValueError("Skill package is too large to revision safely")

                relative = os.path.relpath(path, root).replace(os.sep, "/")
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
                with open(path, "rb") as file:
                    while chunk := file.read(64 * 1024):
                        digest.update(chunk)
                digest.update(b"\0")
        return f"sha256:{digest.hexdigest()}"

    def _require_revision(
        self,
        skill: dict,
        expected_revision: str | None,
    ) -> str:
        revision = self._package_revision(str(skill.get("package_root") or ""))
        normalized_expected = str(expected_revision or "").strip()
        if normalized_expected and normalized_expected != revision:
            raise SkillRevisionMismatchError(
                "Skill revision changed "
                f"(expected {normalized_expected}, current {revision}); "
                "reactivate the Skill."
            )
        return revision

    @staticmethod
    def _serialize_skill(skill: dict) -> dict:
        return {
            field: skill.get(field) for field in _PUBLIC_SKILL_FIELDS if field in skill
        }

    def _load_skill_package(
        self, package_root: str, entry_file: str = "SKILL.md"
    ) -> dict:
        package_root = self._normalize_package_root(package_root)
        entry_path = os.path.join(package_root, entry_file)
        content = _read_utf8_text_limited(
            entry_path,
            subject=f"Skill entry file {entry_file}",
        )

        metadata, instructions = parse_frontmatter(content)
        dir_name = os.path.basename(os.path.normpath(package_root))
        skill_name = self._validate_skill_name(metadata.get("name") or dir_name)
        stat = os.stat(entry_path)
        return {
            "name": skill_name,
            "display_name": str(metadata.get("display_name") or skill_name).strip(),
            "description": str(metadata.get("description") or "").strip(),
            "instructions": instructions,
            "package_root": package_root,
            "entry_file": entry_file,
            "python_project": any(
                os.path.isfile(os.path.join(package_root, filename))
                for filename in (
                    "requirements.txt",
                    "pyproject.toml",
                    "setup.py",
                    "setup.cfg",
                )
            )
            or os.path.isdir(os.path.join(package_root, ".venv")),
            "created_at": dt.datetime.fromtimestamp(
                stat.st_ctime, tz=dt.timezone.utc
            ).isoformat(),
            "updated_at": dt.datetime.fromtimestamp(
                stat.st_mtime, tz=dt.timezone.utc
            ).isoformat(),
        }

    def _read_skill_package(self, package_root: str) -> dict:
        entry = self._find_skill_entry(package_root)
        if entry is None:
            raise ValueError(f"No SKILL.md found in {package_root}")

        skill = self._load_skill_package(entry[0], entry[1])
        return {
            "entry_file": skill.get("entry_file", "SKILL.md"),
            "display_name": skill.get("display_name", ""),
            "description": skill.get("description", ""),
            "instructions": skill.get("instructions", ""),
        }

    def _write_skill_md(
        self, package_root: str, metadata: dict, instructions: str
    ) -> None:
        package_root = self._normalize_package_root(package_root)
        os.makedirs(package_root, exist_ok=True)
        content = build_skill_md(metadata, instructions)
        with open(os.path.join(package_root, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(content)

    def _managed_skill_path(self, skill_name: str) -> str:
        return self._normalize_package_root(os.path.join(self.root, skill_name))

    def _managed_install_root_for_package(self, package_root: str) -> str:
        managed_root = self._normalize_package_root(self.root)
        package_root = self._normalize_package_root(package_root)
        if not package_root or package_root == managed_root:
            return ""

        prefix = f"{managed_root}{os.sep}"
        if not package_root.startswith(prefix):
            return ""

        relative = os.path.relpath(package_root, managed_root)
        top_level = relative.split(os.sep, 1)[0]
        if top_level in ("", ".", ".."):
            return ""
        return os.path.join(managed_root, top_level)

    def _build_preview_target_dir(
        self, base_target_name: str, source_path: str, suffix: str
    ) -> str:
        relative = str(source_path or "").strip().replace("\\", "/").strip("/")
        leaf_name = relative.split("/")[-1] if relative else ""
        target_name = base_target_name
        if leaf_name and leaf_name != base_target_name:
            target_name = f"{base_target_name}-{leaf_name}"
        if suffix:
            target_name = f"{target_name}-{suffix}"
        return os.path.join(self.root, target_name)

    def _preview_skill_candidates(
        self, root_path: str, *, base_target_name: str, suffix: str
    ) -> list[dict]:
        discovered = self._discover_skill_directories(root_path, max_depth=2)
        if not discovered:
            raise ValueError(
                f"No SKILL.md found in {root_path} or its subdirectories (max depth: 2)"
            )

        previews: list[dict] = []
        for package_root, entry_file in discovered:
            skill = self._load_skill_package(package_root, entry_file)
            relative_path = os.path.relpath(package_root, root_path)
            if relative_path in ("", "."):
                relative_path = ""
            skill["source_path"] = relative_path.replace(os.sep, "/")
            skill["package_root"] = self._build_preview_target_dir(
                base_target_name, relative_path, suffix
            )
            previews.append(skill)

        previews.sort(key=lambda item: item["source_path"])
        return [self._serialize_skill_with_source(preview) for preview in previews]

    @staticmethod
    def _serialize_skill_with_source(skill: dict) -> dict:
        data = SkillStore._serialize_skill(skill)
        if "source_path" in skill:
            data["source_path"] = skill["source_path"]
        return data

    def _select_preview_candidates(
        self, previews: list[dict], data: dict
    ) -> list[dict]:
        normalized_paths: list[str] = []
        raw_source_paths = data.get("source_paths", [])
        if isinstance(raw_source_paths, list):
            for source_path in raw_source_paths:
                normalized = (
                    str(source_path or "").strip().replace("\\", "/").strip("/")
                )
                if normalized not in normalized_paths:
                    normalized_paths.append(normalized)

        legacy_source_path = (
            str(data.get("source_path", "") or "").strip().replace("\\", "/").strip("/")
        )
        if legacy_source_path and legacy_source_path not in normalized_paths:
            normalized_paths.append(legacy_source_path)

        if len(previews) == 1 and not normalized_paths:
            return previews

        if not normalized_paths:
            candidates = ", ".join(item["source_path"] or "." for item in previews)
            raise ValueError(
                f"Multiple skills found. Please choose one or more source_paths: {candidates}"
            )

        selected: list[dict] = []
        available = {preview["source_path"]: preview for preview in previews}
        for normalized_path in normalized_paths:
            preview = available.get(normalized_path)
            if preview is None:
                candidates = ", ".join(item["source_path"] or "." for item in previews)
                raise ValueError(
                    f'Invalid source_path "{normalized_path}". Available: {candidates}'
                )
            selected.append(preview)

        return selected

    def _install_preview_candidates(
        self, root_path: str, selected_previews: list[dict]
    ) -> list[dict]:
        target_dirs: list[str] = []
        for preview in selected_previews:
            target_dir = self._normalize_package_root(preview["package_root"])
            if target_dir in target_dirs:
                raise ValueError(f"Duplicate target directory selected: {target_dir}")
            if os.path.exists(target_dir):
                raise ValueError(f"Skill directory already exists: {target_dir}")
            target_dirs.append(target_dir)

        installed_scans: list[dict] = []
        created_dirs: list[str] = []
        try:
            for preview in selected_previews:
                target_dir = self._normalize_package_root(preview["package_root"])
                source_root = self._preview_source_root(
                    root_path, preview["source_path"]
                )
                os.makedirs(os.path.dirname(target_dir), exist_ok=True)
                shutil.copytree(source_root, target_dir)
                created_dirs.append(target_dir)
                installed_scans.append(self.scan_directory(target_dir))
        except Exception:
            for target_dir in created_dirs:
                shutil.rmtree(target_dir, ignore_errors=True)
            raise

        return installed_scans

    def _extract_uploaded_skill_to_temp(self, file_bytes: bytes, tmp_dir: str) -> str:
        extract_dir = os.path.join(tmp_dir, "extracted")
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                self._safe_extract_zip(zf, extract_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError("Uploaded file must be a valid .zip archive") from exc

        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            return os.path.join(extract_dir, entries[0])
        return extract_dir

    @staticmethod
    def _validate_zip_upload_size(file_bytes: bytes) -> None:
        if len(file_bytes) > _MAX_ZIP_COMPRESSED_BYTES:
            raise ValueError(
                "Uploaded archive exceeds the compressed size limit "
                f"({_MAX_ZIP_COMPRESSED_BYTES} bytes)"
            )

    @staticmethod
    def _uploaded_skill_target_stem(filename: str) -> str:
        stem = os.path.splitext(os.path.basename(str(filename or "").strip()))[0]
        safe_stem = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in stem
        ).strip("-_")
        return safe_stem or "uploaded-skill"

    @staticmethod
    def _preview_source_root(root_path: str, source_path: str) -> str:
        normalized = str(source_path or "").strip().replace("\\", "/").strip("/")
        if not normalized:
            return root_path
        return os.path.join(root_path, normalized)

    @staticmethod
    def _resolve_source_subdir_root(root_path: str, source_subdir: str) -> str:
        normalized = str(source_subdir or "").strip().replace("\\", "/").strip("/")
        if not normalized:
            return root_path

        normalized_path = os.path.normpath(normalized)
        if (
            normalized_path.startswith("..")
            or normalized_path == ".."
            or os.path.isabs(normalized_path)
        ):
            raise ValueError("source_subdir must stay within the uploaded archive")

        target_root = os.path.realpath(os.path.join(root_path, normalized_path))
        archive_root = os.path.realpath(root_path)
        if target_root != archive_root and not target_root.startswith(
            f"{archive_root}{os.sep}"
        ):
            raise ValueError("source_subdir must stay within the uploaded archive")
        if not os.path.isdir(target_root):
            raise ValueError(
                f"source_subdir does not exist in the uploaded archive: {normalized}"
            )
        return target_root

    @staticmethod
    def _safe_extract_zip(archive: zipfile.ZipFile, target_dir: str) -> None:
        """Validate and stream-extract a bounded ZIP archive.

        ``ZipFile.extractall`` is intentionally avoided: all metadata limits are
        checked before the first file is written and every member is then copied
        through an explicit byte counter. This prevents path traversal, symlink
        materialization, metadata-only size lies, and decompression bombs.
        """

        target_root = os.path.realpath(target_dir)
        os.makedirs(target_root, exist_ok=True)
        members = archive.infolist()
        if len(members) > _MAX_ZIP_ENTRIES:
            raise ValueError(
                f"Archive contains too many entries (maximum {_MAX_ZIP_ENTRIES})"
            )

        validated: list[tuple[zipfile.ZipInfo, str, bool]] = []
        seen_paths: set[str] = set()
        total_compressed = 0
        total_uncompressed = 0
        for member in members:
            member_name = str(member.filename or "")
            if not member_name or "\x00" in member_name:
                raise ValueError("Archive contains an unsafe empty or NUL path")

            portable_name = member_name.replace("\\", "/")
            normalized = posixpath.normpath(portable_name)
            first_component = normalized.split("/", 1)[0]
            if (
                portable_name.startswith("/")
                or normalized in {"", ".", ".."}
                or normalized.startswith("../")
                or (len(first_component) >= 2 and first_component[1] == ":")
            ):
                raise ValueError(f"Archive contains an unsafe path: {member_name}")

            destination = os.path.realpath(
                os.path.join(target_root, *normalized.split("/"))
            )
            if destination != target_root and not destination.startswith(
                f"{target_root}{os.sep}"
            ):
                raise ValueError(f"Archive contains an unsafe path: {member_name}")

            destination_key = os.path.normcase(destination)
            if destination_key in seen_paths:
                raise ValueError(f"Archive contains a duplicate path: {member_name}")
            seen_paths.add(destination_key)

            unix_mode = (member.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(unix_mode)
            is_directory = member.is_dir() or portable_name.endswith("/")
            if file_type == stat.S_IFLNK:
                raise ValueError(f"Archive contains a symbolic link: {member_name}")
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError(f"Archive contains a non-regular entry: {member_name}")
            if is_directory:
                if member.file_size != 0:
                    raise ValueError(
                        f"Archive directory has unexpected content: {member_name}"
                    )
                validated.append((member, destination, True))
                continue

            if member.file_size < 0 or member.compress_size < 0:
                raise ValueError(
                    f"Archive contains invalid size metadata: {member_name}"
                )
            if member.file_size > _MAX_ZIP_ENTRY_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"Archive entry exceeds the uncompressed size limit: {member_name}"
                )
            if member.file_size and (
                member.compress_size == 0
                or member.file_size / member.compress_size > _MAX_ZIP_COMPRESSION_RATIO
            ):
                raise ValueError(
                    f"Archive entry exceeds the compression ratio limit: {member_name}"
                )
            total_compressed += member.compress_size
            total_uncompressed += member.file_size
            if total_compressed > _MAX_ZIP_COMPRESSED_BYTES:
                raise ValueError("Archive exceeds the compressed size limit")
            if total_uncompressed > _MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                raise ValueError("Archive exceeds the total uncompressed size limit")
            validated.append((member, destination, False))

        if total_uncompressed and (
            total_compressed == 0
            or total_uncompressed / total_compressed > _MAX_ZIP_COMPRESSION_RATIO
        ):
            raise ValueError("Archive exceeds the aggregate compression ratio limit")

        extracted_total = 0
        for member, destination, is_directory in validated:
            if is_directory:
                os.makedirs(destination, mode=0o755, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(destination), mode=0o755, exist_ok=True)
            extracted_entry = 0
            try:
                with (
                    archive.open(member, "r") as source,
                    open(destination, "xb") as target,
                ):
                    while True:
                        chunk = source.read(_ZIP_COPY_CHUNK_BYTES)
                        if not chunk:
                            break
                        extracted_entry += len(chunk)
                        extracted_total += len(chunk)
                        if extracted_entry > _MAX_ZIP_ENTRY_UNCOMPRESSED_BYTES:
                            raise ValueError(
                                "Archive entry exceeds the uncompressed size limit: "
                                f"{member.filename}"
                            )
                        if extracted_total > _MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                            raise ValueError(
                                "Archive exceeds the total uncompressed size limit"
                            )
                        target.write(chunk)
            except Exception:
                try:
                    os.unlink(destination)
                except OSError:
                    pass
                raise
            if extracted_entry != member.file_size:
                raise ValueError(
                    f"Archive entry size changed while extracting: {member.filename}"
                )
            source_mode = (member.external_attr >> 16) & 0o777
            os.chmod(destination, 0o755 if source_mode & 0o111 else 0o644)

    def _resolve_skill_path(
        self, skill: dict, path: str, *, expect_directory: bool
    ) -> tuple[str, str]:
        package_root = self._normalize_package_root(skill.get("package_root", ""))
        if not package_root:
            raise ValueError(f'Skill "{skill.get("name", "")}" has no package_root')

        relative_path = str(path or ".").strip() or "."
        if os.path.isabs(relative_path):
            raise ValueError("path must be relative to the skill package root")

        normalized_relative = os.path.normpath(relative_path)
        if normalized_relative.startswith("..") or normalized_relative == "..":
            raise ValueError("path must stay within the skill package root")

        target_path = os.path.realpath(os.path.join(package_root, normalized_relative))
        if target_path != package_root and not target_path.startswith(
            f"{package_root}{os.sep}"
        ):
            raise ValueError("path must stay within the skill package root")

        if expect_directory:
            if not os.path.isdir(target_path):
                raise ValueError(f"Skill directory not found: {relative_path}")
        else:
            parent_dir = os.path.dirname(target_path) or package_root
            if parent_dir != package_root and not parent_dir.startswith(
                f"{package_root}{os.sep}"
            ):
                raise ValueError("path must stay within the skill package root")

        return target_path, normalized_relative

    @staticmethod
    def _find_skill_entry(path: str) -> Optional[tuple[str, str]]:
        for candidate in ("SKILL.md", "skill.md"):
            if os.path.isfile(os.path.join(path, candidate)):
                return path, candidate
        return None

    def _discover_skill_directories(
        self,
        root_path: str,
        max_depth: int = 2,
        *,
        max_scan_entries: int = _MAX_SKILL_SCAN_ENTRIES,
        max_skills: int = _MAX_DISCOVERED_SKILLS,
    ) -> list[tuple[str, str]]:
        discovered: list[tuple[str, str]] = []
        queue: collections.deque[tuple[str, int]] = collections.deque([(root_path, 0)])
        seen: set[str] = set()
        scanned_entries = 0

        while queue:
            current_path, depth = queue.popleft()
            normalized_path = os.path.abspath(current_path)
            if normalized_path in seen:
                continue
            seen.add(normalized_path)

            found = self._find_skill_entry(normalized_path)
            if found:
                discovered.append(found)
                if len(discovered) > max_skills:
                    raise ValueError(
                        "Skill discovery exceeded the configured package limit"
                    )
                continue

            if depth >= max_depth:
                continue

            try:
                with os.scandir(normalized_path) as iterator:
                    entries = []
                    for entry in iterator:
                        scanned_entries += 1
                        if scanned_entries > max_scan_entries:
                            raise ValueError(
                                "Skill discovery exceeded the configured entry limit"
                            )
                        entries.append(entry)
                entries.sort(key=lambda entry: entry.name)
            except OSError:
                continue

            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    queue.append((entry.path, depth + 1))

        return discovered

    @staticmethod
    def _validate_skill_name(name: str) -> str:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Skill name is required")
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Skill name can only contain letters, numbers, hyphens and underscores"
            )
        if len(name) > 64:
            raise ValueError("Skill name cannot exceed 64 characters")
        return name

    @staticmethod
    def _normalize_package_root(package_root: str) -> str:
        package_root = str(package_root).strip()
        if not package_root:
            return ""
        return os.path.realpath(os.path.abspath(package_root))

    @staticmethod
    def _resolve_create_field(
        data: dict, field: str, imported_skill_data: dict | None, *, default: str
    ) -> str:
        raw_value = data.get(field) if field in data else None
        if raw_value is None:
            if imported_skill_data is not None:
                return str(imported_skill_data.get(field, default) or default)
            return default

        value = str(raw_value or "")
        if imported_skill_data is not None and not value.strip():
            return str(imported_skill_data.get(field, default) or default)
        return value


__all__ = [
    "SkillRevisionMismatchError",
    "SkillStore",
    "build_skill_md",
    "parse_frontmatter",
    "skill_namespace",
]
