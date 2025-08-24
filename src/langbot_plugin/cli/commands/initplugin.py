from __future__ import annotations

import os
import re
import shutil
import subprocess

from langbot_plugin.cli.gen.renderer import render_template, init_plugin_files
from langbot_plugin.cli.utils.form import input_form_values, NAME_REGEXP

# Check if Git is installed
def is_git_available() -> bool:
    try:
        # Check if Git is available by running git --version
        subprocess.run(
            ["git", "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
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
            stderr=subprocess.PIPE
        )
        print(f"Initialized Git repository in {plugin_dir}")
        print(f"初始化 Git 仓库 {plugin_dir}")

    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to initialize Git repository: {e.stderr}")
        print(f"警告：初始化 Git 仓库失败：{e.stderr}")


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
    if not re.match(NAME_REGEXP, plugin_name):
        print(f"!! Invalid plugin name: {plugin_name}")
        print(
            "!! Please use a valid name, which only contains letters, numbers, underscores and hyphens."
        )
        print("!! 请使用一个有效的名称，只能包含字母、数字、下划线和连字符。")
        return

    if os.path.exists(plugin_name):
        # check if this dir is empty
        if os.listdir(plugin_name):
            print(f"!! {plugin_name} is not empty, please use a different name.")
            print("!! 目录不为空，请使用一个不同的名称。")
            return

    print(f"Creating plugin {plugin_name}, anything you input can be modified later.")
    print(f"创建插件 {plugin_name}，任何输入都可以在之后修改。")

    values = {
        "plugin_name": plugin_name,
        "plugin_author": "",
        "plugin_description": "",
        "plugin_label": "",
        "plugin_attr": "",
    }

    input_values = input_form_values(form_fields)
    values.update(input_values)

    values["plugin_attr"] = values["plugin_name"].replace("-", "").replace("_", "")
    values["plugin_label"] = values["plugin_name"].replace("-", " ").replace("_", " ")

    if not os.path.exists(values["plugin_name"]):
        os.makedirs(values["plugin_name"])

    print(f"Creating files in {values['plugin_name']}...")
    print(f"在 {values['plugin_name']} 中创建文件...")

    os.makedirs(f"{values['plugin_name']}/assets", exist_ok=True)

    for file in init_plugin_files:
        content = render_template(f"{file}.example", **values)
        with open(f"{values['plugin_name']}/{file}", "w", encoding="utf-8") as f:
            f.write(content)

    # If Git is available, initialize repository
    if is_git_available():
        init_git_repo(values["plugin_name"])
    else:
        print("Git not found, skipping Git repository initialization.")
        print("请确保 Git 已安装并在 PATH 中可用，跳过 Git 仓库初始化。")

    print(f"Plugin {values['plugin_name']} created successfully.")
    print(f"插件 {values['plugin_name']} 创建成功。")
