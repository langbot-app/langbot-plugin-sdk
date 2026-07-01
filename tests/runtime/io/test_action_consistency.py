"""Tests for scripts/check_action_consistency.py.

The integration test (``test_repo_action_protocol_is_consistent``) is the live
guard: it fails CI if any action is invoked without a registered handler — the
class of bug that shipped ``vector_list`` broken. The unit tests pin the
receiver-direction logic that decides which actions are checkable from this repo.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest  # type: ignore

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_action_consistency.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_action_consistency", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def test_script_exists():
    assert SCRIPT_PATH.is_file()


@pytest.mark.parametrize(
    ("enum_name", "expected"),
    [
        ("PluginToRuntimeAction", "Runtime"),
        ("RuntimeToPluginAction", "Plugin"),
        ("LangBotToRuntimeAction", "Runtime"),
        ("RuntimeToLangBotAction", "LangBot"),
        ("CommonAction", None),
        ("NotAnActionEnum", None),
    ],
)
def test_action_receiver(enum_name, expected):
    assert checker.action_receiver(enum_name) == expected


@pytest.mark.parametrize(
    ("enum_name", "in_repo"),
    [
        ("PluginToRuntimeAction", True),
        ("RuntimeToPluginAction", True),
        ("LangBotToRuntimeAction", True),
        ("CommonAction", True),
        ("RuntimeToLangBotAction", False),  # receiver is the external LangBot host
    ],
)
def test_receiver_in_repo(enum_name, in_repo):
    assert checker.receiver_in_repo(enum_name) is in_repo


def test_enum_members_load():
    enums = checker.load_enum_members()
    assert "PluginToRuntimeAction" in enums
    # VECTOR_LIST must exist on the enum (referenced by the proxy + runtime forwarder).
    assert "VECTOR_LIST" in enums["PluginToRuntimeAction"]


def test_repo_action_protocol_is_consistent(capsys):
    """Every in-repo-received action that is invoked must have a handler."""
    exit_code = checker.main()
    captured = capsys.readouterr()
    assert exit_code == 0, (
        f"Action protocol consistency check failed:\n{captured.out}\n{captured.err}"
    )
