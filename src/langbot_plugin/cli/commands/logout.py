from __future__ import annotations

import json
from pathlib import Path
from langbot_plugin.cli.i18n import cli_print


def logout_process() -> None:
    """
    Implement LangBot CLI logout process

    Process:
    1. Remove configuration file
    2. Display logout success message
    """

    try:
        config_file = Path.home() / ".langbot" / "cli" / "config.json"

        if config_file.exists():
            config_file.unlink()
            cli_print("logout_successful")
            cli_print("config_file_removed", config_file)
        else:
            cli_print("already_logged_out")

    except Exception as e:
        cli_print("logout_error", e)
