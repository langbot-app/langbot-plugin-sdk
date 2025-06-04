from __future__ import annotations

from typing import Any

import jinja2
import pydantic.v1 as pydantic

from jinja2 import Environment, PackageLoader

def get_template_environment():
    """
    获取Jinja2模板环境
    """
    return Environment(
        loader=PackageLoader('langbot_plugin.assets', 'templates')
    )

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
    target_dir: str = pydantic.Field(description="The target directory of the component")
    template_files: list[str] = pydantic.Field(description="The template files of the component")
    form_fields: list[dict[str, Any]] = pydantic.Field(description="The form fields of the component")


component_types = [
    ComponentType(
        type_name="EventListener",
        target_dir="components/event_listener",
        template_files=[
            "default.yaml",
            "default.py",
        ],
        form_fields=[]
    )
]