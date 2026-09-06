from __future__ import annotations

import os
from unittest import mock

import pytest

from langbot_plugin.skill_store import (
    SkillRevisionMismatchError,
    SkillStore,
    skill_namespace,
)


def test_generic_store_uses_an_execution_independent_root(tmp_path):
    store = SkillStore(tmp_path / "skills").scoped("workspace-a")

    created = store.create_skill(
        {
            "name": "docs-only",
            "description": "Read-only guidance",
            "instructions": "Read references/guide.md.",
        }
    )
    store.write_skill_file(
        "docs-only",
        "references/guide.md",
        "# Guide\n\nNo execution needed.",
    )

    snapshot = store.get_skill_snapshot("docs-only")
    assert snapshot is not None
    assert snapshot["revision"].startswith("stat-v1:")
    assert created["package_root"].startswith(store.root + os.sep)

    listed = store.list_skill_resources(
        "docs-only",
        "references",
        expected_revision=snapshot["revision"],
    )
    assert listed["entries"][0]["mime_type"] == "text/markdown"

    resource = store.read_skill_resource(
        "docs-only",
        "references/guide.md",
        expected_revision=snapshot["revision"],
    )
    assert resource["content"].startswith("# Guide")
    assert resource["revision"] == snapshot["revision"]


def test_skill_namespace_is_stable_and_workspace_scoped():
    first = skill_namespace("instance-a", "workspace-a")

    assert first == skill_namespace("instance-a", "workspace-a")
    assert first != skill_namespace("instance-a", "workspace-b")
    assert first.startswith("ws-")


def test_generic_store_rejects_stale_revision_and_symbolic_links(tmp_path):
    store = SkillStore(tmp_path / "skills")
    store.create_skill({"name": "safe", "instructions": "Use the guide."})
    store.write_skill_file("safe", "guide.md", "first")
    snapshot = store.get_skill_snapshot("safe")
    assert snapshot is not None

    store.write_skill_file("safe", "guide.md", "second")
    with pytest.raises(SkillRevisionMismatchError, match="reactivate"):
        store.read_skill_resource(
            "safe",
            "guide.md",
            expected_revision=snapshot["revision"],
        )

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "skills" / "safe" / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this platform")
    with pytest.raises(ValueError, match="symbolic links"):
        store.get_skill_snapshot("safe")


def test_revision_uses_metadata_and_resource_reads_scan_once(tmp_path):
    store = SkillStore(tmp_path / "skills")
    store.create_skill({"name": "docs", "instructions": "Read guide.md."})
    store.write_skill_file("docs", "guide.md", "content")
    snapshot = store.get_skill_snapshot("docs")
    assert snapshot is not None

    with (
        mock.patch.object(
            store,
            "_package_revision",
            wraps=store._package_revision,
        ) as revision_mock,
        mock.patch.object(
            store,
            "_require_skill",
            wraps=store._require_skill,
        ) as require_skill_mock,
    ):
        result = store.read_skill_resource(
            "docs",
            "guide.md",
            expected_revision=snapshot["revision"],
        )

    assert result["content"] == "content"
    assert revision_mock.call_count == 1
    assert require_skill_mock.call_count == 1

    with mock.patch("builtins.open", side_effect=AssertionError("content read")):
        revision = store._package_revision(snapshot["package_root"])
    assert revision.startswith("stat-v1:")


def test_generic_store_imports_only_from_a_fenced_source_root(tmp_path):
    store = SkillStore(tmp_path / "skills").scoped("workspace-a")
    workspace = tmp_path / "workspace"
    draft = workspace / "draft"
    draft.mkdir(parents=True)
    (draft / "SKILL.md").write_text(
        "---\nname: draft\n---\n\nFollow the guide.",
        encoding="utf-8",
    )
    (draft / "guide.md").write_text("Imported resource", encoding="utf-8")

    scanned = store.scan_import_directory(str(draft), source_root=str(workspace))
    imported = store.import_skill_directory(
        str(draft),
        {
            "name": scanned["name"],
            "description": scanned["description"],
            "instructions": scanned["instructions"],
        },
        source_root=str(workspace),
    )
    assert imported["name"] == "draft"
    assert (
        store.read_skill_resource("draft", "guide.md")["content"] == "Imported resource"
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("Outside", encoding="utf-8")
    with pytest.raises(ValueError, match="trusted source root"):
        store.scan_import_directory(str(outside), source_root=str(workspace))


def test_generic_store_rejects_symlinks_during_import(tmp_path):
    store = SkillStore(tmp_path / "skills").scoped("workspace-a")
    workspace = tmp_path / "workspace"
    draft = workspace / "draft"
    draft.mkdir(parents=True)
    (draft / "SKILL.md").write_text("---\nname: draft\n---\n\nDraft", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (draft / "linked.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this platform")

    with pytest.raises(ValueError, match="symbolic links"):
        store.import_skill_directory(
            str(draft),
            {"name": "draft", "instructions": "Draft"},
            source_root=str(workspace),
        )
