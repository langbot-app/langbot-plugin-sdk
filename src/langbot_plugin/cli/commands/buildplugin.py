from __future__ import annotations

import os
import zipfile
import fnmatch
from pathlib import Path
from typing import List

from langbot_plugin.utils.discover.engine import ComponentDiscoveryEngine
from langbot_plugin.cli.i18n import cli_print


def parse_gitignore(gitignore_path: str) -> List[str]:
    """Parse .gitignore file and return list of patterns."""
    patterns = []
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return patterns


def should_ignore(path: str, gitignore_patterns: List[str]) -> bool:
    """Check if a path should be ignored based on .gitignore patterns."""
    # Convert path to use forward slashes for consistency
    normalized_path = str(Path(path)).replace(os.sep, "/")

    for pattern in gitignore_patterns:
        # Skip empty patterns
        if not pattern:
            continue

        # Handle directory patterns (ending with /)
        if pattern.endswith("/"):
            dir_pattern = pattern[:-1]  # Remove trailing slash
            # Check if the path ends with the directory pattern
            if (
                normalized_path.endswith(f"/{dir_pattern}")
                or normalized_path == dir_pattern
            ):
                return True
            # Check if any part of the path matches the directory pattern
            path_parts = normalized_path.split("/")
            if dir_pattern in path_parts:
                return True
        # Handle patterns starting with / (root-relative)
        elif pattern.startswith("/"):
            root_pattern = pattern[1:]  # Remove leading slash
            if normalized_path.startswith(root_pattern):
                return True
        # Handle patterns with wildcards
        elif "*" in pattern or "?" in pattern:
            if fnmatch.fnmatch(normalized_path, pattern):
                return True
            # Also check if the basename matches
            if fnmatch.fnmatch(os.path.basename(path), pattern):
                return True
        # Handle exact file/directory matches
        else:
            # Check if the path ends with the pattern
            if normalized_path.endswith(f"/{pattern}") or normalized_path == pattern:
                return True
            # Check if any part of the path matches the pattern
            path_parts = normalized_path.split("/")
            if pattern in path_parts:
                return True

    return False


def build_plugin_process(output_dir: str) -> str:
    if not os.path.exists("manifest.yaml"):
        cli_print("manifest_not_found")
        return

    cli_print("building_plugin", output_dir)

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    discovery_engine = ComponentDiscoveryEngine()

    plugin_manifest = discovery_engine.load_component_manifest(
        path="manifest.yaml",
        owner="builtin",
        no_save=True,
    )

    plugin_author = plugin_manifest.metadata.author
    plugin_name = plugin_manifest.metadata.name
    plugin_version = plugin_manifest.metadata.version

    zipfile_path = os.path.join(
        output_dir, f"{plugin_author}-{plugin_name}-{plugin_version}.lbpkg"
    )

    # Parse .gitignore patterns
    gitignore_patterns = parse_gitignore(".gitignore")

    # Additional files/directories to always exclude
    always_exclude = {
        ".env",
        "__pycache__",
        ".pytest_cache",
        ".coverage",
        "*.pyc",
        "*.pyo",
        "*.pyd",
    }

    # copy all files to zip, except files listed in .gitignore
    with zipfile.ZipFile(zipfile_path, "w") as zipf:
        for root, dirs, files in os.walk("."):
            # Remove ignored directories from dirs list to prevent walking into them
            dirs_to_remove = []
            for d in dirs:
                dir_path = os.path.join(root, d)
                relative_dir_path = os.path.relpath(dir_path, ".")
                if should_ignore(relative_dir_path, gitignore_patterns):
                    dirs_to_remove.append(d)
                    cli_print("skipping_ignored_dir", relative_dir_path)

            # Remove ignored directories
            for d in dirs_to_remove:
                dirs.remove(d)

            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, ".")

                # Skip if file should be ignored
                if should_ignore(relative_path, gitignore_patterns):
                    cli_print("skipping_ignored_file", relative_path)
                    continue

                # Skip if file is in always_exclude
                if any(fnmatch.fnmatch(file, pattern) for pattern in always_exclude):
                    cli_print("skipping_excluded_file", relative_path)
                    continue

                # Add file to zip
                try:
                    zipf.write(file_path, relative_path)
                    cli_print("file_added", relative_path)
                except Exception as e:
                    cli_print("file_add_error", relative_path, e)

    cli_print("plugin_built", zipfile_path)
    return zipfile_path
