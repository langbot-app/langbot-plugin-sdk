from __future__ import annotations

import tomllib
from pathlib import Path


def test_stable_release_metadata_is_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    source_version = (
        (root / "src/langbot_plugin/version.py").read_text(encoding="utf-8").strip()
    )

    assert project["project"]["version"] == "0.6.9"
    assert source_version == '__version__ = "0.6.9"'
