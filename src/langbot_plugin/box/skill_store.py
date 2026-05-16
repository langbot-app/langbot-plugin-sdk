from __future__ import annotations

import datetime as dt
import io
import os
import posixpath
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import yaml


_FRONTMATTER_FIELDS = (
    'name',
    'display_name',
    'description',
)

_PUBLIC_SKILL_FIELDS = (
    'name',
    'display_name',
    'description',
    'instructions',
    'package_root',
    'entry_file',
    'created_at',
    'updated_at',
)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith('---'):
        return {}, content

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return {}, content

    for index in range(1, len(lines)):
        if lines[index].strip() == '---':
            metadata_text = ''.join(lines[1:index])
            instructions = ''.join(lines[index + 1 :]).lstrip('\n')
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

    frontmatter_text = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    return f'---\n{frontmatter_text}\n---\n\n{instructions}'


class BoxSkillStore:
    """Skill package storage owned by the Box runtime process."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def update_config(self, config: dict) -> None:
        self._config = config or {}

    @property
    def root(self) -> str:
        local_config = self._config.get('local') or {}
        host_root = str(local_config.get('host_root') or './data/box').strip()
        skills_root = str(local_config.get('skills_root') or 'skills').strip()

        host_root_path = Path(host_root).expanduser()
        if not host_root_path.is_absolute():
            host_root_path = Path.cwd() / host_root_path
        host_root_path = host_root_path.resolve()

        skills_root_path = Path(skills_root).expanduser()
        if not skills_root_path.is_absolute():
            skills_root_path = host_root_path / skills_root_path
        return str(skills_root_path.resolve())

    def list_skills(self) -> list[dict]:
        os.makedirs(self.root, exist_ok=True)
        skills: list[dict] = []
        for package_root, entry_file in self._discover_skill_directories(self.root, max_depth=6):
            try:
                skills.append(self._load_skill_package(package_root, entry_file))
            except Exception:
                continue
        skills.sort(key=lambda item: item.get('updated_at', ''), reverse=True)
        return [self._serialize_skill(skill) for skill in skills]

    def get_skill(self, skill_name: str) -> Optional[dict]:
        for skill in self.list_skills():
            if skill.get('name') == skill_name:
                return skill
        return None

    def create_skill(self, data: dict) -> dict:
        name = self._validate_skill_name(data.get('name', ''))
        if self.get_skill(name):
            raise ValueError(f'Skill with name "{name}" already exists')

        package_root = self._normalize_package_root(data.get('package_root', ''))
        managed_root = self._managed_skill_path(name)
        target_root = managed_root
        imported_skill_data: dict | None = None

        if package_root and self._managed_install_root_for_package(package_root):
            if not os.path.isdir(package_root):
                raise ValueError(f'Directory does not exist: {package_root}')
            target_root = package_root
            imported_skill_data = self._read_skill_package(target_root)
        elif package_root and package_root != managed_root:
            if not os.path.isdir(package_root):
                raise ValueError(f'Directory does not exist: {package_root}')
            if os.path.exists(managed_root):
                raise ValueError(f'Skill directory already exists: {managed_root}')
            os.makedirs(os.path.dirname(managed_root), exist_ok=True)
            shutil.copytree(package_root, managed_root)
            imported_skill_data = self._read_skill_package(managed_root)
        else:
            os.makedirs(managed_root, exist_ok=True)

        metadata = {
            'name': name,
            'display_name': self._resolve_create_field(data, 'display_name', imported_skill_data, default=''),
            'description': self._resolve_create_field(data, 'description', imported_skill_data, default=''),
        }
        instructions = self._resolve_create_field(data, 'instructions', imported_skill_data, default='')
        self._write_skill_md(target_root, metadata, instructions)

        created = self.get_skill(name)
        if not created:
            raise ValueError(f'Failed to create skill "{name}"')
        return created

    def update_skill(self, skill_name: str, data: dict) -> dict:
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f'Skill "{skill_name}" not found')

        requested_name = str(data.get('name', skill['name']) or skill['name']).strip()
        if requested_name != skill['name']:
            raise ValueError('Renaming skills is not supported')

        requested_package_root = str(data.get('package_root', '') or '').strip()
        existing_package_root = self._normalize_package_root(skill['package_root'])
        if requested_package_root and self._normalize_package_root(requested_package_root) != existing_package_root:
            raise ValueError('Updating package_root is not supported; recreate the skill to import a different package')

        metadata = {
            'name': skill['name'],
            'display_name': data.get('display_name', skill.get('display_name', '')),
            'description': data.get('description', skill.get('description', '')),
        }
        instructions = str(data.get('instructions', skill.get('instructions', '')) or '')
        self._write_skill_md(skill['package_root'], metadata, instructions)

        updated = self.get_skill(skill_name)
        if not updated:
            raise ValueError(f'Skill "{skill_name}" not found after update')
        return updated

    def delete_skill(self, skill_name: str) -> dict:
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f'Skill "{skill_name}" not found')

        package_root = self._normalize_package_root(skill['package_root'])
        managed_install_root = self._managed_install_root_for_package(package_root)
        if not managed_install_root:
            raise ValueError('Only managed skills under the Box skills root can be deleted')

        shutil.rmtree(managed_install_root, ignore_errors=True)
        return {'deleted': skill_name}

    def scan_directory(self, path: str) -> dict:
        if not os.path.isdir(path):
            raise ValueError(f'Directory does not exist: {path}')

        discovered = self._discover_skill_directories(path, max_depth=2)
        if not discovered:
            raise ValueError(f'No SKILL.md found in {path} or its subdirectories (max depth: 2)')
        if len(discovered) > 1:
            candidates = ', '.join(found_path for found_path, _entry in discovered)
            raise ValueError(
                f'Multiple skill directories found in {path}. Please choose a more specific path: {candidates}'
            )

        package_root, entry_file = discovered[0]
        return self._load_skill_package(package_root, entry_file)

    def list_skill_files(
        self,
        skill_name: str,
        path: str = '.',
        include_hidden: bool = False,
        max_entries: int = 200,
    ) -> dict:
        skill = self._require_skill(skill_name)
        target_dir, relative_path = self._resolve_skill_path(skill, path, expect_directory=True)
        entries: list[dict] = []
        with os.scandir(target_dir) as iterator:
            for entry in sorted(iterator, key=lambda item: item.name):
                if not include_hidden and entry.name.startswith('.'):
                    continue
                entry_rel_path = entry.name if relative_path in ('', '.') else os.path.join(relative_path, entry.name)
                is_dir = entry.is_dir()
                entries.append(
                    {
                        'path': entry_rel_path.replace(os.sep, '/'),
                        'name': entry.name,
                        'is_dir': is_dir,
                        'size': None if is_dir else entry.stat().st_size,
                    }
                )
                if len(entries) >= max_entries:
                    break

        return {
            'skill': {'name': skill['name']},
            'base_path': '.' if relative_path in ('', '.') else relative_path.replace(os.sep, '/'),
            'entries': entries,
            'truncated': len(entries) >= max_entries,
        }

    def read_skill_file(self, skill_name: str, path: str) -> dict:
        skill = self._require_skill(skill_name)
        target_path, relative_path = self._resolve_skill_path(skill, path, expect_directory=False)
        if not os.path.isfile(target_path):
            raise ValueError(f'Skill file not found: {relative_path}')

        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError as exc:
            raise ValueError(f'Skill file is not valid UTF-8 text: {relative_path}') from exc

        return {
            'skill': {'name': skill['name']},
            'path': relative_path.replace(os.sep, '/'),
            'content': content,
        }

    def write_skill_file(self, skill_name: str, path: str, content: str) -> dict:
        skill = self._require_skill(skill_name)
        target_path, relative_path = self._resolve_skill_path(skill, path, expect_directory=False)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return {
            'skill': {'name': skill['name']},
            'path': relative_path.replace(os.sep, '/'),
            'bytes_written': len(content.encode('utf-8')),
        }

    def preview_zip_upload(self, *, file_bytes: bytes, filename: str, source_subdir: str = '') -> list[dict]:
        if not file_bytes:
            raise ValueError('Uploaded file is empty')

        tmp_dir = tempfile.mkdtemp(prefix='langbot_box_skill_preview_')
        try:
            skill_root = self._extract_uploaded_skill_to_temp(file_bytes, tmp_dir)
            skill_root = self._resolve_source_subdir_root(skill_root, source_subdir)
            return self._preview_skill_candidates(
                skill_root,
                base_target_name=self._uploaded_skill_target_stem(filename),
                suffix='upload',
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def install_zip_upload(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        source_paths: list[str] | None = None,
        source_path: str = '',
        source_subdir: str = '',
    ) -> list[dict]:
        if not file_bytes:
            raise ValueError('Uploaded file is empty')

        tmp_dir = tempfile.mkdtemp(prefix='langbot_box_skill_upload_')
        try:
            skill_root = self._extract_uploaded_skill_to_temp(file_bytes, tmp_dir)
            skill_root = self._resolve_source_subdir_root(skill_root, source_subdir)
            previews = self._preview_skill_candidates(
                skill_root,
                base_target_name=self._uploaded_skill_target_stem(filename),
                suffix='upload',
            )
            selected_previews = self._select_preview_candidates(
                previews,
                {'source_paths': source_paths or [], 'source_path': source_path},
            )
            scanned = self._install_preview_candidates(skill_root, selected_previews)
            return [self.get_skill(skill['name']) or self._serialize_skill(skill) for skill in scanned]
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _require_skill(self, skill_name: str) -> dict:
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f'Skill "{skill_name}" not found')
        return skill

    @staticmethod
    def _serialize_skill(skill: dict) -> dict:
        return {field: skill.get(field) for field in _PUBLIC_SKILL_FIELDS if field in skill}

    def _load_skill_package(self, package_root: str, entry_file: str = 'SKILL.md') -> dict:
        package_root = self._normalize_package_root(package_root)
        entry_path = os.path.join(package_root, entry_file)
        with open(entry_path, 'r', encoding='utf-8') as f:
            content = f.read()

        metadata, instructions = parse_frontmatter(content)
        dir_name = os.path.basename(os.path.normpath(package_root))
        stat = os.stat(entry_path)
        return {
            'name': str(metadata.get('name') or dir_name).strip(),
            'display_name': str(metadata.get('display_name') or metadata.get('name') or dir_name).strip(),
            'description': str(metadata.get('description') or '').strip(),
            'instructions': instructions,
            'package_root': package_root,
            'entry_file': entry_file,
            'created_at': dt.datetime.fromtimestamp(stat.st_ctime, tz=dt.timezone.utc).isoformat(),
            'updated_at': dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc).isoformat(),
        }

    def _read_skill_package(self, package_root: str) -> dict:
        entry = self._find_skill_entry(package_root)
        if entry is None:
            raise ValueError(f'No SKILL.md found in {package_root}')

        skill = self._load_skill_package(entry[0], entry[1])
        return {
            'entry_file': skill.get('entry_file', 'SKILL.md'),
            'display_name': skill.get('display_name', ''),
            'description': skill.get('description', ''),
            'instructions': skill.get('instructions', ''),
        }

    def _write_skill_md(self, package_root: str, metadata: dict, instructions: str) -> None:
        package_root = self._normalize_package_root(package_root)
        os.makedirs(package_root, exist_ok=True)
        content = build_skill_md(metadata, instructions)
        with open(os.path.join(package_root, 'SKILL.md'), 'w', encoding='utf-8') as f:
            f.write(content)

    def _managed_skill_path(self, skill_name: str) -> str:
        return self._normalize_package_root(os.path.join(self.root, skill_name))

    def _managed_install_root_for_package(self, package_root: str) -> str:
        managed_root = self._normalize_package_root(self.root)
        package_root = self._normalize_package_root(package_root)
        if not package_root or package_root == managed_root:
            return ''

        prefix = f'{managed_root}{os.sep}'
        if not package_root.startswith(prefix):
            return ''

        relative = os.path.relpath(package_root, managed_root)
        top_level = relative.split(os.sep, 1)[0]
        if top_level in ('', '.', '..'):
            return ''
        return os.path.join(managed_root, top_level)

    def _build_preview_target_dir(self, base_target_name: str, source_path: str, suffix: str) -> str:
        relative = str(source_path or '').strip().replace('\\', '/').strip('/')
        leaf_name = relative.split('/')[-1] if relative else ''
        target_name = base_target_name
        if leaf_name and leaf_name != base_target_name:
            target_name = f'{base_target_name}-{leaf_name}'
        if suffix:
            target_name = f'{target_name}-{suffix}'
        return os.path.join(self.root, target_name)

    def _preview_skill_candidates(self, root_path: str, *, base_target_name: str, suffix: str) -> list[dict]:
        discovered = self._discover_skill_directories(root_path, max_depth=2)
        if not discovered:
            raise ValueError(f'No SKILL.md found in {root_path} or its subdirectories (max depth: 2)')

        previews: list[dict] = []
        for package_root, entry_file in discovered:
            skill = self._load_skill_package(package_root, entry_file)
            relative_path = os.path.relpath(package_root, root_path)
            if relative_path in ('', '.'):
                relative_path = ''
            skill['source_path'] = relative_path.replace(os.sep, '/')
            skill['package_root'] = self._build_preview_target_dir(base_target_name, relative_path, suffix)
            previews.append(skill)

        previews.sort(key=lambda item: item['source_path'])
        return [self._serialize_skill_with_source(preview) for preview in previews]

    @staticmethod
    def _serialize_skill_with_source(skill: dict) -> dict:
        data = BoxSkillStore._serialize_skill(skill)
        if 'source_path' in skill:
            data['source_path'] = skill['source_path']
        return data

    def _select_preview_candidates(self, previews: list[dict], data: dict) -> list[dict]:
        normalized_paths: list[str] = []
        raw_source_paths = data.get('source_paths', [])
        if isinstance(raw_source_paths, list):
            for source_path in raw_source_paths:
                normalized = str(source_path or '').strip().replace('\\', '/').strip('/')
                if normalized not in normalized_paths:
                    normalized_paths.append(normalized)

        legacy_source_path = str(data.get('source_path', '') or '').strip().replace('\\', '/').strip('/')
        if legacy_source_path and legacy_source_path not in normalized_paths:
            normalized_paths.append(legacy_source_path)

        if len(previews) == 1 and not normalized_paths:
            return previews

        if not normalized_paths:
            candidates = ', '.join(item['source_path'] or '.' for item in previews)
            raise ValueError(f'Multiple skills found. Please choose one or more source_paths: {candidates}')

        selected: list[dict] = []
        available = {preview['source_path']: preview for preview in previews}
        for normalized_path in normalized_paths:
            preview = available.get(normalized_path)
            if preview is None:
                candidates = ', '.join(item['source_path'] or '.' for item in previews)
                raise ValueError(f'Invalid source_path "{normalized_path}". Available: {candidates}')
            selected.append(preview)

        return selected

    def _install_preview_candidates(self, root_path: str, selected_previews: list[dict]) -> list[dict]:
        target_dirs: list[str] = []
        for preview in selected_previews:
            target_dir = self._normalize_package_root(preview['package_root'])
            if target_dir in target_dirs:
                raise ValueError(f'Duplicate target directory selected: {target_dir}')
            if os.path.exists(target_dir):
                raise ValueError(f'Skill directory already exists: {target_dir}')
            target_dirs.append(target_dir)

        installed_scans: list[dict] = []
        created_dirs: list[str] = []
        try:
            for preview in selected_previews:
                target_dir = self._normalize_package_root(preview['package_root'])
                source_root = self._preview_source_root(root_path, preview['source_path'])
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
        extract_dir = os.path.join(tmp_dir, 'extracted')
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), 'r') as zf:
                self._safe_extract_zip(zf, extract_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError('Uploaded file must be a valid .zip archive') from exc

        entries = os.listdir(extract_dir)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            return os.path.join(extract_dir, entries[0])
        return extract_dir

    @staticmethod
    def _uploaded_skill_target_stem(filename: str) -> str:
        stem = os.path.splitext(os.path.basename(str(filename or '').strip()))[0]
        safe_stem = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '-' for ch in stem).strip('-_')
        return safe_stem or 'uploaded-skill'

    @staticmethod
    def _preview_source_root(root_path: str, source_path: str) -> str:
        normalized = str(source_path or '').strip().replace('\\', '/').strip('/')
        if not normalized:
            return root_path
        return os.path.join(root_path, normalized)

    @staticmethod
    def _resolve_source_subdir_root(root_path: str, source_subdir: str) -> str:
        normalized = str(source_subdir or '').strip().replace('\\', '/').strip('/')
        if not normalized:
            return root_path

        normalized_path = os.path.normpath(normalized)
        if normalized_path.startswith('..') or normalized_path == '..' or os.path.isabs(normalized_path):
            raise ValueError('source_subdir must stay within the uploaded archive')

        target_root = os.path.realpath(os.path.join(root_path, normalized_path))
        archive_root = os.path.realpath(root_path)
        if target_root != archive_root and not target_root.startswith(f'{archive_root}{os.sep}'):
            raise ValueError('source_subdir must stay within the uploaded archive')
        if not os.path.isdir(target_root):
            raise ValueError(f'source_subdir does not exist in the uploaded archive: {normalized}')
        return target_root

    @staticmethod
    def _safe_extract_zip(archive: zipfile.ZipFile, target_dir: str) -> None:
        target_root = os.path.realpath(target_dir)
        os.makedirs(target_root, exist_ok=True)

        for member in archive.infolist():
            member_name = member.filename
            if not member_name or member_name.endswith('/'):
                continue

            normalized = posixpath.normpath(member_name)
            if normalized.startswith('../') or normalized == '..' or os.path.isabs(normalized):
                raise ValueError(f'Archive contains an unsafe path: {member_name}')

            destination = os.path.realpath(os.path.join(target_root, normalized))
            if destination != target_root and not destination.startswith(f'{target_root}{os.sep}'):
                raise ValueError(f'Archive contains an unsafe path: {member_name}')

        archive.extractall(target_root)

    def _resolve_skill_path(self, skill: dict, path: str, *, expect_directory: bool) -> tuple[str, str]:
        package_root = self._normalize_package_root(skill.get('package_root', ''))
        if not package_root:
            raise ValueError(f'Skill "{skill.get("name", "")}" has no package_root')

        relative_path = str(path or '.').strip() or '.'
        if os.path.isabs(relative_path):
            raise ValueError('path must be relative to the skill package root')

        normalized_relative = os.path.normpath(relative_path)
        if normalized_relative.startswith('..') or normalized_relative == '..':
            raise ValueError('path must stay within the skill package root')

        target_path = os.path.realpath(os.path.join(package_root, normalized_relative))
        if target_path != package_root and not target_path.startswith(f'{package_root}{os.sep}'):
            raise ValueError('path must stay within the skill package root')

        if expect_directory:
            if not os.path.isdir(target_path):
                raise ValueError(f'Skill directory not found: {relative_path}')
        else:
            parent_dir = os.path.dirname(target_path) or package_root
            if parent_dir != package_root and not parent_dir.startswith(f'{package_root}{os.sep}'):
                raise ValueError('path must stay within the skill package root')

        return target_path, normalized_relative

    @staticmethod
    def _find_skill_entry(path: str) -> Optional[tuple[str, str]]:
        for candidate in ('SKILL.md', 'skill.md'):
            if os.path.isfile(os.path.join(path, candidate)):
                return path, candidate
        return None

    def _discover_skill_directories(self, root_path: str, max_depth: int = 2) -> list[tuple[str, str]]:
        discovered: list[tuple[str, str]] = []
        queue: list[tuple[str, int]] = [(root_path, 0)]
        seen: set[str] = set()

        while queue:
            current_path, depth = queue.pop(0)
            normalized_path = os.path.abspath(current_path)
            if normalized_path in seen:
                continue
            seen.add(normalized_path)

            found = self._find_skill_entry(normalized_path)
            if found:
                discovered.append(found)
                continue

            if depth >= max_depth:
                continue

            try:
                entries = sorted(os.scandir(normalized_path), key=lambda entry: entry.name)
            except OSError:
                continue

            for entry in entries:
                if entry.is_dir():
                    queue.append((entry.path, depth + 1))

        return discovered

    @staticmethod
    def _validate_skill_name(name: str) -> str:
        name = str(name or '').strip()
        if not name:
            raise ValueError('Skill name is required')
        if not name.replace('-', '').replace('_', '').isalnum():
            raise ValueError('Skill name can only contain letters, numbers, hyphens and underscores')
        if len(name) > 64:
            raise ValueError('Skill name cannot exceed 64 characters')
        return name

    @staticmethod
    def _normalize_package_root(package_root: str) -> str:
        package_root = str(package_root).strip()
        if not package_root:
            return ''
        return os.path.realpath(os.path.abspath(package_root))

    @staticmethod
    def _resolve_create_field(data: dict, field: str, imported_skill_data: dict | None, *, default: str) -> str:
        raw_value = data.get(field) if field in data else None
        if raw_value is None:
            if imported_skill_data is not None:
                return str(imported_skill_data.get(field, default) or default)
            return default

        value = str(raw_value or '')
        if imported_skill_data is not None and not value.strip():
            return str(imported_skill_data.get(field, default) or default)
        return value
