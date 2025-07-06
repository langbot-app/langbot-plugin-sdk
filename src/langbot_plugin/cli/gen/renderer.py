from __future__ import annotations

from typing import Any, Callable

import jinja2
import pydantic

from jinja2 import Environment, PackageLoader
from langbot_plugin.cli.utils.form import NAME_REGEXP, NUMBER_LOWER_UNDERSCORE_REGEXP


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


files = [
    "manifest.yaml",
    "main.py",
    "README.md",
    "requirements.txt",
    ".env.example",
    ".gitignore",
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
                    "zh_CN": "工具名称",
                },
                "required": True,
                "format": {
                    "regexp": NUMBER_LOWER_UNDERSCORE_REGEXP,
                    "error": {
                        "en_US": "Invalid tool name, please use a valid name, which only contains letters, numbers, underscores and hyphens, and start with a letter.",
                        "zh_CN": "无效的工具名称，请使用一个有效的名称，只能包含字母、数字、下划线和连字符，且以字母开头。",
                    },
                },
            },
            {
                "name": "tool_description",
                "label": {
                    "en_US": "Tool description",
                    "zh_CN": "工具描述",
                },
                "required": True,
            },
        ],
        input_post_process=tool_component_input_post_process,
    ),
]
