"""Temporary wire compatibility for rolling upgrades from Skill-aware Box.

This module is deliberately isolated from Box models, clients, and runtime.
It exists only so an old Core can keep talking to a newly deployed Box while
the Core replicas are rolled forward.

TODO(next-major): delete this module and the legacy action registration after
the rolling-upgrade window for the pre-decoupling protocol has closed. Upgrade
Box replicas before Core replicas while this bridge is required.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Callable

from langbot_plugin.entities.io.actions.enums import ActionType
from langbot_plugin.entities.io.context import ActionContext
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.skill_store import SkillStore

from .models import BoxHostMountMode, BoxMountSpec, DEFAULT_BOX_MOUNT_PATH
from .tenancy import box_namespace


class LegacySkillAction(ActionType):
    LIST_SKILLS = "box_list_skills"
    GET_SKILL = "box_get_skill"
    CREATE_SKILL = "box_create_skill"
    UPDATE_SKILL = "box_update_skill"
    DELETE_SKILL = "box_delete_skill"
    SCAN_SKILL_DIRECTORY = "box_scan_skill_directory"
    LIST_SKILL_FILES = "box_list_skill_files"
    READ_SKILL_FILE = "box_read_skill_file"
    WRITE_SKILL_FILE = "box_write_skill_file"
    PREVIEW_SKILL_ZIP = "box_preview_skill_zip"
    INSTALL_SKILL_ZIP = "box_install_skill_zip"


def _legacy_store_root(config: dict) -> str:
    local = config.get("local") or {}
    host_root = Path(str(local.get("host_root") or "./data/box")).expanduser()
    if not host_root.is_absolute():
        host_root = Path.cwd() / host_root
    skills_root = Path(str(local.get("skills_root") or "skills")).expanduser()
    if not skills_root.is_absolute():
        skills_root = host_root / skills_root
    return os.fspath(skills_root.resolve())


class LegacySkillCompat:
    """Lazy adapter used only by the old Skill RPC wire protocol."""

    def __init__(self, config_provider: Callable[[], dict]):
        self._config_provider = config_provider
        self._root: str | None = None
        self._store: SkillStore | None = None
        self._lock = asyncio.Lock()

    def _current_store(self) -> SkillStore:
        root = _legacy_store_root(self._config_provider())
        if self._store is None or self._root != root:
            self._root = root
            self._store = SkillStore(root)
        return self._store

    def _scoped_store(self, context: ActionContext) -> SkillStore:
        return self._current_store().scoped(box_namespace(context))

    async def call(
        self,
        context: ActionContext,
        method_name: str,
        *args,
        **kwargs,
    ):
        async with self._lock:
            store = self._scoped_store(context)
            method = getattr(store, method_name)
            return await asyncio.to_thread(method, *args, **kwargs)

    async def normalize_spec_payload(
        self,
        data: dict,
        context: ActionContext,
    ) -> dict:
        """Translate old ``skill_name`` into a generic read-only mount."""

        payload = dict(data)
        skill_name = str(payload.pop("skill_name", "") or "").strip()
        if not skill_name:
            return payload

        mount_path = f"{DEFAULT_BOX_MOUNT_PATH}/.skills/{skill_name}"
        mounts = [BoxMountSpec.model_validate(item) for item in payload.get("extra_mounts", [])]
        if not any(mount.mount_path == mount_path for mount in mounts):
            package_root = await self.call(
                context,
                "resolve_skill_package_root",
                skill_name,
            )
            mounts.append(
                BoxMountSpec(
                    host_path=package_root,
                    mount_path=mount_path,
                    mode=BoxHostMountMode.READ_ONLY,
                )
            )
        payload["extra_mounts"] = [mount.model_dump(mode="json") for mount in mounts]
        return payload


def register_legacy_skill_actions(
    handler,
    compat_provider: Callable[[], LegacySkillCompat],
    context_provider: Callable[[], ActionContext],
) -> None:
    """Register only the retired old-Core Skill RPC surface."""

    async def call(method_name: str, *args, **kwargs):
        return await compat_provider().call(
            context_provider(),
            method_name,
            *args,
            **kwargs,
        )

    @handler.action(LegacySkillAction.LIST_SKILLS)
    async def list_skills(data: dict) -> ActionResponse:
        return ActionResponse.success({"skills": await call("list_skills")})

    @handler.action(LegacySkillAction.GET_SKILL)
    async def get_skill(data: dict) -> ActionResponse:
        return ActionResponse.success(
            {"skill": await call("get_skill", data["name"])}
        )

    @handler.action(LegacySkillAction.CREATE_SKILL)
    async def create_skill(data: dict) -> ActionResponse:
        try:
            skill = await call("create_skill", data["skill"])
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success({"skill": skill})

    @handler.action(LegacySkillAction.UPDATE_SKILL)
    async def update_skill(data: dict) -> ActionResponse:
        try:
            skill = await call("update_skill", data["name"], data["skill"])
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success({"skill": skill})

    @handler.action(LegacySkillAction.DELETE_SKILL)
    async def delete_skill(data: dict) -> ActionResponse:
        try:
            result = await call("delete_skill", data["name"])
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success(result)

    @handler.action(LegacySkillAction.SCAN_SKILL_DIRECTORY)
    async def scan_skill_directory(data: dict) -> ActionResponse:
        try:
            skill = await call("scan_directory", data["path"])
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success(skill)

    @handler.action(LegacySkillAction.LIST_SKILL_FILES)
    async def list_skill_files(data: dict) -> ActionResponse:
        try:
            result = await call(
                "list_skill_files",
                data["name"],
                data.get("path", "."),
                include_hidden=bool(data.get("include_hidden", False)),
                max_entries=int(data.get("max_entries", 200)),
            )
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success(result)

    @handler.action(LegacySkillAction.READ_SKILL_FILE)
    async def read_skill_file(data: dict) -> ActionResponse:
        try:
            result = await call("read_skill_file", data["name"], data["path"])
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success(result)

    @handler.action(LegacySkillAction.WRITE_SKILL_FILE)
    async def write_skill_file(data: dict) -> ActionResponse:
        try:
            result = await call(
                "write_skill_file",
                data["name"],
                data["path"],
                data.get("content", ""),
            )
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success(result)

    @handler.action(LegacySkillAction.PREVIEW_SKILL_ZIP)
    async def preview_skill_zip(data: dict) -> ActionResponse:
        try:
            file_bytes = await handler.read_local_file(data["file_key"])
            await handler.delete_local_file(data["file_key"])
            result = await call(
                "preview_zip_upload",
                file_bytes=file_bytes,
                filename=data.get("filename", "skill.zip"),
                source_subdir=data.get("source_subdir") or "",
                target_suffix=data.get("target_suffix", "upload"),
            )
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success({"skills": result})

    @handler.action(LegacySkillAction.INSTALL_SKILL_ZIP)
    async def install_skill_zip(data: dict) -> ActionResponse:
        try:
            file_bytes = await handler.read_local_file(data["file_key"])
            await handler.delete_local_file(data["file_key"])
            result = await call(
                "install_zip_upload",
                file_bytes=file_bytes,
                filename=data.get("filename", "skill.zip"),
                source_paths=data.get("source_paths") or [],
                source_path=data.get("source_path") or "",
                source_subdir=data.get("source_subdir") or "",
                target_suffix=data.get("target_suffix", "upload"),
            )
        except Exception as exc:
            return ActionResponse.error(f"BoxValidationError: {exc}")
        return ActionResponse.success({"skills": result})


__all__ = [
    "LegacySkillAction",
    "LegacySkillCompat",
    "register_legacy_skill_actions",
]
