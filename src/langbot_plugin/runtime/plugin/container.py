# Plugin runtime container

from __future__ import annotations

import typing
import enum
import pydantic

from langbot_plugin.api.definition.base import BasePlugin
from langbot_plugin.api.definition.components.base import BaseComponent
from langbot_plugin.api.definition.components.manifest import ComponentManifest


class RuntimeContainerStatus(enum.Enum):
    """插件容器状态"""

    UNMOUNTED = "unmounted"
    """未加载进内存"""

    MOUNTED = "mounted"
    """已加载进内存，所有位于运行时记录中的 RuntimeContainer 至少是这个状态"""

    INITIALIZED = "initialized"
    """已初始化"""


class PluginContainer(pydantic.BaseModel):
    """The container for running plugins."""

    manifest: ComponentManifest
    """插件清单"""

    plugin_instance: BasePlugin
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

    def model_dump(self):
        return {
            "manifest": self.manifest.model_dump(),
            "plugin_instance": None,  # not serializable
            "enabled": self.enabled,
            "priority": self.priority,
            "plugin_config": self.plugin_config,
            "status": self.status.value,
            "components": [component.model_dump() for component in self.components]
        }


class ComponentContainer(pydantic.BaseModel):
    """The container for running components."""

    manifest: ComponentManifest
    """组件清单"""

    component_instance: BaseComponent
    """组件实例"""

    component_config: dict[str, typing.Any]
    """组件配置"""

    class Config:
        arbitrary_types_allowed = True

    def model_dump(self):
        return {
            "manifest": self.manifest.model_dump(),
            "component_instance": None,  # not serializable
            "component_config": self.component_config,
        }


PluginContainer.update_forward_refs()
