from __future__ import annotations

import ast
from pathlib import Path

import yaml

RUNNER_DEMO_ROOT = Path(__file__).resolve().parents[1] / "RunnerDemo"
RUNTIME_SOURCES = (
    RUNNER_DEMO_ROOT / "main.py",
    RUNNER_DEMO_ROOT / "components" / "runner" / "community.py",
    RUNNER_DEMO_ROOT / "components" / "runner" / "observer.py",
)


def test_runner_demo_manifest_declares_certified_shared_runtime() -> None:
    manifest = yaml.safe_load((RUNNER_DEMO_ROOT / "manifest.yaml").read_text(encoding="utf-8"))

    assert manifest["execution"]["sharedRuntime"] == "shared-runtime-v1"


def test_runner_demo_runtime_sources_avoid_process_and_module_state() -> None:
    forbidden_imports = {"os", "subprocess", "multiprocessing"}

    for source_path in RUNTIME_SOURCES:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        module_assignments = [
            node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        ]
        imported_roots = {
            alias.name.split(".", 1)[0] for node in tree.body if isinstance(node, ast.Import) for alias in node.names
        } | {node.module.split(".", 1)[0] for node in tree.body if isinstance(node, ast.ImportFrom) and node.module}

        assert not module_assignments, source_path
        assert not (imported_roots & forbidden_imports), source_path
        assert not any(isinstance(node, ast.Global) for node in ast.walk(tree)), source_path
