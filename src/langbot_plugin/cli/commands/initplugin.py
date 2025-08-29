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
    if plugin_name == "":
        print("未指定插件名称，将在当前目录生成插件内容")
        print("No plugin name specified, generating content in current directory")
        plugin_dir = os.getcwd()
        plugin_dir_name = os.path.basename(plugin_dir)
    else:
        # When a name is provided, use that name as both the directory and logical name.
        plugin_dir = plugin_name
        plugin_dir_name = plugin_name

    if not re.match(NAME_REGEXP, plugin_dir_name):
        print(f"!! Invalid plugin name: {plugin_dir_name}")
        print(
            "!! Please use a valid name, which only contains letters, numbers, underscores and hyphens."
        )
        print("!! 请使用一个有效的名称，只能包含字母、数字、下划线和连字符。")
        return

    # check if directory exists and is not empty
    if os.path.exists(plugin_dir):
        # list directory contents (excluding hidden files)
        dir_contents = [f for f in os.listdir(plugin_dir) if not f.startswith('.')]
        if dir_contents: 
            print(f"!! 目录 {plugin_dir} 不为空，请使用其他名称或清空目录")
            print(f"!! Directory {plugin_dir} is not empty, use a different name or empty it")
            return
    else:
        # only create directory if a plugin name is specified and the directory does not exist
        os.makedirs(plugin_dir, exist_ok=True)

    print(f"Creating plugin {plugin_dir_name}, anything you input can be modified later.")
    print(f"创建插件 {plugin_dir_name}，任何输入都可以在之后修改。")

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

    print(f"Creating files in {values['plugin_name']}...")
    print(f"在 {values['plugin_name']} 中创建文件...")

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
        print("Git not found, skipping Git repository initialization.")
        print("请确保 Git 已安装并在 PATH 中可用，跳过 Git 仓库初始化。")

    print(f"插件 {plugin_dir_name} 创建成功（目录：{plugin_dir}）")
    print(f"Plugin {plugin_dir_name} created successfully (directory: {plugin_dir})")
