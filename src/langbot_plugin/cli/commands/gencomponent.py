from __future__ import annotations

import os

import yaml

from langbot_plugin.cli.gen.renderer import component_types, render_template
from langbot_plugin.cli.utils.form import input_form_values
from langbot_plugin.cli.gen.renderer import simple_render


def generate_component_process(component_type: str) -> None:
    if not os.path.exists("manifest.yaml"):
        print("!! Please run this command in the root directory of the plugin.")
        print("!! 请在插件的根目录下运行此命令。")
        return

    component_type_obj = None

    for component_type_obj in component_types:
        if component_type_obj.type_name == component_type:
            print(f"Generating component {component_type_obj.type_name}...")
            component_type_obj = component_type_obj
            break
    else:
        print(f"!! Component type {component_type} not found.")
        print("!! Please use one of the following component types:")
        for component_type_obj in component_types:
            print(f"!! - {component_type_obj.type_name}")
        return

    values = {}

    if component_type_obj.form_fields:
        values = input_form_values(component_type_obj.form_fields)

    values = component_type_obj.input_post_process(values)  # type: ignore

    if not os.path.exists("components"):
        os.makedirs("components")
        with open("components/__init__.py", "w", encoding="utf-8") as f:
            f.write("")

    if not os.path.exists(component_type_obj.target_dir):
        os.makedirs(component_type_obj.target_dir)

    if not os.path.exists(f"{component_type_obj.target_dir}/__init__.py"):
        with open(
            f"{component_type_obj.target_dir}/__init__.py", "w", encoding="utf-8"
        ) as f:
            f.write("")

    # render templates
    for file in component_type_obj.template_files:
        content = render_template(
            f"{component_type_obj.target_dir}/{file}.example", **values
        )

        rendered_file_name = simple_render(file, **values)
        with open(
            f"{component_type_obj.target_dir}/{rendered_file_name}",
            "w",
            encoding="utf-8",
        ) as f:
            f.write(content)

    # update plugin manifest
    with open("manifest.yaml", "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    plugin_components = manifest["spec"]["components"]

    if component_type_obj.type_name not in plugin_components:
        plugin_components[component_type_obj.type_name] = {
            "fromDirs": [
                {
                    "path": f"{component_type_obj.target_dir}/",
                }
            ]
        }

    with open("manifest.yaml", "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, sort_keys=False)

    print(f"Component {component_type_obj.type_name} generated successfully.")
    print(f"组件 {component_type_obj.type_name} 生成成功。")
