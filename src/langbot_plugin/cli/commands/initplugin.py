from __future__ import annotations

import os
import re
import shutil
import subprocess

from langbot_plugin.cli.gen.renderer import render_template, init_plugin_files
from langbot_plugin.cli.utils.form import input_form_values, NAME_REGEXP
from langbot_plugin.cli.i18n import cli_print, t


# Check if Git is installed
def is_git_available() -> bool:
    try:
        # Check if Git is available by running git --version
        subprocess.run(
            ["git", "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# Initialize Git repository and add basic configuration
def init_git_repo(plugin_dir: str) -> None:
    try:
        # Initialize Git repository
        subprocess.run(
            ["git", "init"],
            cwd=plugin_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        cli_print("git_repo_initialized", plugin_dir)

    except subprocess.CalledProcessError as e:
        cli_print("git_init_warning", e.stderr)


form_fields = [
    {
        "name": "plugin_author",
        "label": {
            "en_US": "Plugin author",
            "zh_Hans": "插件作者",
        },
        "required": True,
        "format": {
            "regexp": NAME_REGEXP,
            "error": {
                "en_US": "Invalid plugin author, please use a valid name, which only contains letters, numbers, underscores and hyphens.",
                "zh_Hans": "无效的插件作者，请使用一个有效的名称，只能包含字母、数字、下划线和连字符。",
            },
        },
    },
    {
        "name": "plugin_description",
        "label": {
            "en_US": "Plugin description",
            "zh_Hans": "插件描述",
        },
        "required": True,
    },
]


def init_plugin_process(
    plugin_name: str,
) -> None:
    if plugin_name == "":
        cli_print("no_plugin_name")
        plugin_dir = os.getcwd()
        plugin_dir_name = os.path.basename(plugin_dir)
    else:
        # When a name is provided, use that name as both the directory and logical name.
        plugin_dir = plugin_name
        plugin_dir_name = plugin_name

    if not re.match(NAME_REGEXP, plugin_dir_name):
        print("!! " + t("invalid_plugin_name", plugin_dir_name))
        print("!! " + t("invalid_name_format"))
        return

    # check if directory exists and is not empty
    if os.path.exists(plugin_dir):
        # list directory contents (excluding hidden files)
        dir_contents = [f for f in os.listdir(plugin_dir) if not f.startswith(".")]
        if dir_contents:
            print("!! " + t("directory_not_empty", plugin_dir))
            return
    else:
        # only create directory if a plugin name is specified and the directory does not exist
        os.makedirs(plugin_dir, exist_ok=True)

    cli_print("creating_plugin", plugin_dir_name)

    values = {
        "plugin_name": plugin_dir_name,
        "plugin_author": "",
        "plugin_description": "",
        "plugin_label": "",
        "plugin_attr": "",
    }

    input_values = input_form_values(form_fields)
    values.update(input_values)

    values["plugin_attr"] = values["plugin_name"].replace("-", "").replace("_", "")
    values["plugin_label"] = values["plugin_name"].replace("-", " ").replace("_", " ")

    cli_print("creating_files", values["plugin_name"])

    assets_dir = os.path.join(plugin_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    for file in init_plugin_files:
        content = render_template(f"{file}.example", **values)
        file_path = os.path.join(plugin_dir, file)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    # If Git is available, initialize repository
    if is_git_available():
        # init_git_repo(values["plugin_name"])
        init_git_repo(plugin_dir)
    else:
        cli_print("git_not_found")

    cli_print("plugin_created", plugin_dir_name, plugin_dir)
