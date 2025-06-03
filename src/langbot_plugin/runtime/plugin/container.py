# Plugin runtime container

from __future__ import annotations

import typing
import enum
import pydantic.v1 as pydantic

from langbot_plugin.api.definition.base import BasePlugin
from langbot_plugin.api.definition.components.base import BaseComponent
from langbot_plugin.api.definition.components.manifest import ComponentManifest


class RuntimeContainerStatus(enum.Enum):
    """插件容器状态"""

    UNMOUNTED = 'unmounted'
    """未加载进内存"""

    MOUNTED = 'mounted'
    """已加载进内存，所有位于运行时记录中的 RuntimeContainer 至少是这个状态"""

    INITIALIZED = 'initialized'
    """已初始化"""


class PluginContainer(pydantic.BaseModel):
    """The container for running plugins."""

    manifest: ComponentManifest
    """插件清单"""
    
    plugin_instance: BasePlugin | None
    """插件实例"""
    
    enabled: bool
    """插件是否启用"""
    
    priority: int
    """插件优先级"""

    plugin_config: dict[str, typing.Any]
    """插件配置"""

    status: RuntimeContainerStatus
    """插件容器状态"""

    components: list[ComponentContainer]
    """组件容器列表"""
    
    class Config:
        arbitrary_types_allowed = True


class ComponentContainer(pydantic.BaseModel):
    """The container for running components."""

    manifest: ComponentManifest
    """组件清单"""

    component_instance: BaseComponent | None
    """组件实例"""

    component_config: dict[str, typing.Any]
    """组件配置"""

    class Config:
        arbitrary_types_allowed = True
