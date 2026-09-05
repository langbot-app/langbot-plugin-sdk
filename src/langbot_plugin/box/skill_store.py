"""Backward-compatible Box adapter for the execution-independent Skill store."""

from __future__ import annotations

import os
from pathlib import Path

from ..skill_store import SkillStore, build_skill_md, parse_frontmatter


def skill_store_root_from_box_config(config: dict | None = None) -> str:
    """Resolve the legacy Box configuration into a Skill store root."""

    local_config = (config or {}).get("local") or {}
    host_root = str(local_config.get("host_root") or "./data/box").strip()
    skills_root = str(local_config.get("skills_root") or "skills").strip()

    host_root_path = Path(host_root).expanduser()
    if not host_root_path.is_absolute():
        host_root_path = Path.cwd() / host_root_path
    host_root_path = host_root_path.resolve()

    skills_root_path = Path(skills_root).expanduser()
    if not skills_root_path.is_absolute():
        skills_root_path = host_root_path / skills_root_path
    return os.fspath(skills_root_path.resolve())


class BoxSkillStore(SkillStore):
    """Compatibility adapter for callers that still pass Box configuration."""

    def __init__(self, config: dict | None = None, *, namespace: str | None = None):
        self._config = config or {}
        super().__init__(
            skill_store_root_from_box_config(self._config),
            namespace=namespace,
        )

    def scoped(self, namespace: str) -> BoxSkillStore:
        normalized = str(namespace or "").strip()
        if (
            not normalized
            or "/" in normalized
            or "\\" in normalized
            or normalized in {".", ".."}
        ):
            raise ValueError("Invalid Box skill namespace")
        return BoxSkillStore(self._config, namespace=normalized)

    def update_config(self, config: dict) -> None:
        self._config = config or {}
        self._base_root = Path(skill_store_root_from_box_config(self._config)).resolve()


__all__ = [
    "BoxSkillStore",
    "SkillStore",
    "build_skill_md",
    "parse_frontmatter",
    "skill_store_root_from_box_config",
]
