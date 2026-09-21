"""Keep migrated plugins' suites isolated, as in their production processes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("plugin", ["LocalAgent", "RunnerDemo"])
def test_migrated_runner_suite(plugin, tmp_path):
    plugin_root = ROOT / plugin
    manifest = yaml.safe_load((plugin_root / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["metadata"]["repository"] == (
        f"https://github.com/langbot-app/langbot-plugins/tree/main/Runner/{plugin}"
    )
    evidence_dir = Path(os.environ.get("RUNNER_EVIDENCE_DIR") or tmp_path)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            os.environ.get("LOCALAGENT_TEST_PYTHON", sys.executable) if plugin == "LocalAgent" else sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={evidence_dir / (plugin + '.xml')}",
        ],
        cwd=plugin_root,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        timeout=180,
    )
    (evidence_dir / f"{plugin}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
