from __future__ import annotations

import typing
import importlib
import os
import pydantic
import sys


class I18nString(pydantic.BaseModel):
    """国际化字符串"""

    en_US: str
    """英文"""

    zh_Hans: typing.Optional[str] = None
    """中文"""

    ja_JP: typing.Optional[str] = None
    """日文"""

    def to_dict(self) -> dict:
        """转换为字典"""
        dic = {}
        if self.en_US is not None:
            dic["en_US"] = self.en_US
        if self.zh_Hans is not None:
            dic["zh_Hans"] = self.zh_Hans
        if self.ja_JP is not None:
            dic["ja_JP"] = self.ja_JP
        return dic


class Metadata(pydantic.BaseModel):
    """元数据"""

    name: str
    """名称"""

    label: I18nString
    """标签"""

    description: typing.Optional[I18nString] = None
    """描述"""

    version: typing.Optional[str] = None
    """版本"""

    icon: typing.Optional[str] = None
    """图标"""

    author: typing.Optional[str] = None
    """作者"""

    repository: typing.Optional[str] = None
    """仓库"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if self.description is None:
            self.description = I18nString(en_US="")

        if self.icon is None:
            self.icon = ""


class PythonExecution(pydantic.BaseModel):
    """Python执行"""

    path: str
    """路径"""

    attr: str
    """属性"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if self.path.startswith("./"):
            self.path = self.path[2:]


class Execution(pydantic.BaseModel):
    """执行"""

    python: PythonExecution
    """Python执行"""


class ComponentManifest(pydantic.BaseModel):
    """组件清单"""

    owner: str
    """组件所属"""

    manifest: typing.Dict[str, typing.Any]
    """组件清单内容"""

    rel_path: str
    """组件清单相对main.py的路径"""

    _rel_dir: str
    """组件清单相对main.py的目录"""

    _metadata: Metadata
    """组件元数据"""

    _spec: typing.Dict[str, typing.Any]
    """组件规格"""

    _execution: Execution | None
    """组件执行"""

    def __init__(
        self, owner: str, manifest: typing.Dict[str, typing.Any], rel_path: str
    ):
        super().__init__(
            owner=owner,
            manifest=manifest,
            rel_path=rel_path,
        )
        self._metadata = Metadata(**manifest["metadata"])
        self._spec = manifest["spec"]
        self._rel_dir = os.path.dirname(rel_path)
        self._execution = (
            Execution(**manifest["execution"]) if "execution" in manifest else None
        )

    @classmethod
    def is_component_manifest(cls, manifest: typing.Dict[str, typing.Any]) -> bool:
        """判断是否为组件清单"""
        return (
            "apiVersion" in manifest
            and "kind" in manifest
            and "metadata" in manifest
            and "spec" in manifest
        )

    @property
    def kind(self) -> str:
        """组件类型"""
        return self.manifest["kind"]

    @property
    def metadata(self) -> Metadata:
        """组件元数据"""
        return self._metadata

    @property
    def spec(self) -> typing.Dict[str, typing.Any]:
        """组件规格"""
        return self._spec

    @property
    def execution(self) -> Execution | None:
        """组件可执行文件信息"""
        return self._execution

    @property
    def icon_rel_path(self) -> str | None:
        """图标相对路径"""
        return (
            os.path.join(self._rel_dir, self.metadata.icon)
            if self.metadata.icon is not None and self.metadata.icon.strip() != ""
            else None
        )

    def get_python_component_class(self) -> typing.Type[typing.Any]:
        """获取Python组件类"""
        if self.execution is None:
            raise ValueError("Execution is not set")
        module_path = os.path.join(self._rel_dir, self.execution.python.path)
        if module_path.endswith(".py"):
            module_path = module_path[:-3]
        module_path = module_path.replace("/", ".").replace("\\", ".")
        pwd = os.getcwd()
        sys.path.append(pwd)
        module = importlib.import_module(module_path)
        return getattr(module, self.execution.python.attr)

    def to_plain_dict(self) -> dict:
        """转换为平铺字典"""
        return {
            "name": self.metadata.name,
            "label": self.metadata.label.to_dict(),
            "description": self.metadata.description.to_dict()
            if self.metadata.description is not None
            else None,
            "icon": self.metadata.icon,
            "spec": self.spec,
        }
