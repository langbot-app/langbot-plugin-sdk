from __future__ import annotations

from typing import Any, Callable

import pydantic

from jinja2 import Environment, PackageLoader
from langbot_plugin.cli.utils.form import NUMBER_LOWER_UNDERSCORE_REGEXP


def get_template_environment():
    """
    获取Jinja2模板环境
    """
    return Environment(loader=PackageLoader("langbot_plugin.assets", "templates"))


def render_template(template_name: str, **context) -> str:
    """
    渲染模板

    Args:
        template_name: 模板文件名
        **context: 模板变量

    Returns:
        str: 渲染后的内容
    """
    env = get_template_environment()
    template = env.get_template(template_name)
    return template.render(**context)


def simple_render(
    origin_text: str,
    **context,
) -> str:
    return origin_text.format(**context)


init_plugin_files = [
    "manifest.yaml",
    "main.py",
    "README.md",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "assets/icon.svg",
]


class ComponentType(pydantic.BaseModel):
    type_name: str = pydantic.Field(description="The name of the component type")
    target_dir: str = pydantic.Field(
        description="The target directory of the component"
    )
    template_files: list[str] = pydantic.Field(
        description="The template files of the component"
    )
    form_fields: list[dict[str, Any]] = pydantic.Field(
        description="The form fields of the component"
    )
    input_post_process: Callable[[dict[str, Any]], dict[str, Any]] = pydantic.Field(
        description="The input post process of the component",
        default=lambda x: x,
    )


def tool_component_input_post_process(values: dict[str, Any]) -> dict[str, Any]:
    result = {
        "tool_name": values["tool_name"],
        "tool_label": values["tool_name"],
        "tool_description": values["tool_description"],
        "tool_attr": values["tool_name"],
    }

    python_attr_valid_name = "".join(
        word.capitalize() for word in values["tool_name"].split("_")
    )
    result["tool_label"] = python_attr_valid_name
    result["tool_attr"] = python_attr_valid_name
    return result


def command_component_input_post_process(values: dict[str, Any]) -> dict[str, Any]:
    result = {
        "cmd_name": values["cmd_name"],
        "cmd_label": values["cmd_name"],
        "cmd_description": values["cmd_description"],
        "cmd_attr": values["cmd_name"],
    }

    python_attr_valid_name = "".join(
        word.capitalize() for word in values["cmd_name"].split("_")
    )
    result["cmd_label"] = python_attr_valid_name
    result["cmd_attr"] = python_attr_valid_name
    return result


component_types = [
    ComponentType(
        type_name="EventListener",
        target_dir="components/event_listener",
        template_files=[
            "default.yaml",
            "default.py",
        ],
        form_fields=[],
    ),
    ComponentType(
        type_name="Tool",
        target_dir="components/tools",
        template_files=[
            "{tool_name}.yaml",
            "{tool_name}.py",
        ],
        form_fields=[
            {
                "name": "tool_name",
                "label": {
                    "en_US": "Tool name",
                    "zh_Hans": "工具名称",
                    "zh_Hant": "工具名稱",
                    "ja_JP": "ツール名",
                },
                "required": True,
                "format": {
                    "regexp": NUMBER_LOWER_UNDERSCORE_REGEXP,
                    "error": {
                        "en_US": "Invalid tool name, please use a valid name, which only contains lowercase letters, numbers, underscores and hyphens, and start with a letter.",
                        "zh_Hans": "无效的工具名称，请使用一个有效的名称，只能包含小写字母、数字、下划线和连字符，且以字母开头。",
                        "zh_Hant": "無效的工具名稱，請使用一個有效的名稱，只能包含小寫字母、數字、下劃線和連字符，且以字母開頭。",
                        "ja_JP": "無効なツール名です。有効な名前を使用してください。小文字、数字、アンダースコア、ハイフンのみを使用し、先頭は文字でなければなりません。",
                    },
                },
            },
            {
                "name": "tool_description",
                "label": {
                    "en_US": "Tool description",
                    "zh_Hans": "工具描述",
                    "zh_Hant": "工具描述",
                    "ja_JP": "ツールの説明",
                },
                "required": True,
            },
        ],
        input_post_process=tool_component_input_post_process,
    ),
    ComponentType(
        type_name="Command",
        target_dir="components/commands",
        template_files=[
            "{cmd_name}.yaml",
            "{cmd_name}.py",
        ],
        form_fields=[
            {
                "name": "cmd_name",
                "label": {
                    "en_US": "Command name",
                    "zh_Hans": "命令名称",
                    "zh_Hant": "命令名稱",
                    "ja_JP": "コマンド名",
                },
                "required": True,
                "format": {
                    "regexp": NUMBER_LOWER_UNDERSCORE_REGEXP,
                    "error": {
                        "en_US": "Invalid command name, please use a valid name, which only contains lowercase letters, numbers, underscores and hyphens, and start with a letter.",
                        "zh_Hans": "无效的命令名称，请使用一个有效的名称，只能包含小写字母、数字、下划线和连字符，且以字母开头。",
                        "zh_Hant": "無效的命令名稱，請使用一個有效的名稱，只能包含小寫字母、數字、下劃線和連字符，且以字母開頭。",
                        "ja_JP": "無効なコマンド名です。有効な名前を使用してください。小文字、数字、アンダースコア、ハイフンのみを使用し、先頭は文字でなければなりません。",
                    },
                },
            },
            {
                "name": "cmd_description",
                "label": {
                    "en_US": "Command description",
                    "zh_Hans": "命令描述",
                    "zh_Hant": "命令描述",
                    "ja_JP": "コマンドの説明",
                },
                "required": True,
            },
        ],
        input_post_process=command_component_input_post_process,
    ),
]
