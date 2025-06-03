from __future__ import annotations

import os
import re
from langbot_plugin.assets.templates.plugin import (
    plugin_manifest_template,
    main_py_template,
    readme_md_template,
    requirements_txt_template,
    dot_env_example_template,
    gitignore_template,
)

name_regexp = r"^[a-zA-Z0-9_-]+$"

form_fields = [
    {
        "name": "plugin_author",
        "label": {
            "en_US": "Plugin author",
            "zh_CN": "插件作者",
        },
        "required": True,
        "format": {
            "regexp": name_regexp,
            "error": {
                "en_US": "Invalid plugin author, please use a valid name, which only contains letters, numbers, underscores and hyphens.",
                "zh_CN": "无效的插件作者，请使用一个有效的名称，只能包含字母、数字、下划线和连字符。",
            },
        },
    },
    {
        "name": "plugin_description",
        "label": {
            "en_US": "Plugin description",
            "zh_CN": "插件描述",
        },
        "required": True,
    },
]


def init_plugin_process(
    plugin_name: str,
) -> None:
    if not re.match(name_regexp, plugin_name):
        print(f"!! Invalid plugin name: {plugin_name}")
        print(
            "!! Please use a valid name, which only contains letters, numbers, underscores and hyphens."
        )
        print("!! 请使用一个有效的名称，只能包含字母、数字、下划线和连字符。")
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

    for field in form_fields:
        if field["required"]:
            while True:
                value = input(f"{field['label']['en_US']}: ")  # type: ignore
                if "format" in field and "regexp" in field["format"]:  # type: ignore
                    if not re.match(field["format"]["regexp"], value):  # type: ignore
                        print(f"!! {field['format']['error']['en_US']}")  # type: ignore
                        print(f"!! {field['format']['error']['zh_CN']}")  # type: ignore
                        continue
                break
            values[field["name"]] = value  # type: ignore
        else:
            value = input(f"{field['label']['en_US']}: ")  # type: ignore
            values[field["name"]] = value  # type: ignore

    values["plugin_attr"] = values["plugin_name"].replace("-", "").replace("_", "")
    values["plugin_label"] = values["plugin_name"].replace("-", " ").replace("_", " ")

    plugin_manifest = plugin_manifest_template.render(values)
    main_py = main_py_template.render(values)
    readme_md = readme_md_template.render(values)
    requirements_txt = requirements_txt_template.render(values)
    dot_env_example = dot_env_example_template.render(values)
    gitignore = gitignore_template.render(values)

    if not os.path.exists(values["plugin_name"]):
        os.makedirs(values["plugin_name"])

    with open(f"{values['plugin_name']}/manifest.yaml", "w", encoding="utf-8") as f:
        f.write(plugin_manifest)
    with open(f"{values['plugin_name']}/main.py", "w", encoding="utf-8") as f:
        f.write(main_py)
    with open(f"{values['plugin_name']}/README.md", "w", encoding="utf-8") as f:
        f.write(readme_md)
    with open(f"{values['plugin_name']}/requirements.txt", "w", encoding="utf-8") as f:
        f.write(requirements_txt)
    with open(f"{values['plugin_name']}/.env.example", "w", encoding="utf-8") as f:
        f.write(dot_env_example)
    with open(f"{values['plugin_name']}/.gitignore", "w", encoding="utf-8") as f:
        f.write(gitignore)

    print(f"Plugin {values['plugin_name']} created successfully.")
    print(f"插件 {values['plugin_name']} 创建成功。")
