from __future__ import annotations

from typing import Any

import pydantic

from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.api.entities.events import BaseEventModel
import langbot_plugin.api.entities.events as events_module


global_eid_index = 0


class EventContext(pydantic.BaseModel):
    """事件上下文, 保存此次事件运行的信息"""

    eid: int = 0
    """事件编号"""

    event_name: str
    """事件名称"""

    event: pydantic.SerializeAsAny[BaseEventModel]
    """此次事件的对象，具体类型为handler注册时指定监听的类型，可查看events.py中的定义"""

    is_prevent_default: bool = False
    """是否阻止默认行为"""

    is_prevent_postorder: bool = False
    """是否阻止后续插件的执行"""

    return_value: dict[str, list[Any]] = pydantic.Field(default_factory=dict)
    """ 返回值 
    示例:
    {
        "example": [
            'value1',
            'value2',
            3,
            4,
            {
                'key1': 'value1',
            },
            ['value1', 'value2']
        ]
    }
    """

    # ========== 插件可调用的 API ==========

    def add_return(self, key: str, ret):
        """添加返回值"""
        if key not in self.return_value:
            self.return_value[key] = []
        self.return_value[key].append(ret)

    async def reply(self, message_chain: platform_message.MessageChain):
        """回复此次消息请求

        Args:
            message_chain (platform.types.MessageChain): 源平台的消息链，若用户使用的不是源平台适配器，程序也能自动转换为目标平台消息链
        """
        # TODO 添加 at_sender 和 quote_origin 参数

        # TODO impl

    async def send_message(
        self, target_type: str, target_id: str, message: platform_message.MessageChain
    ):
        """主动发送消息

        Args:
            target_type (str): 目标类型，`person`或`group`
            target_id (str): 目标ID
            message (platform.types.MessageChain): 源平台的消息链，若用户使用的不是源平台适配器，程序也能自动转换为目标平台消息链
        """
        # TODO impl

    def prevent_default(self):
        """阻止默认行为"""
        self.is_prevent_default = True

    def prevent_postorder(self):
        """阻止后续插件执行"""
        self.is_prevent_postorder = True

    # ========== 以下是内部保留方法，插件不应调用 ==========

    def get_return(self, key: str) -> list:
        """获取key的所有返回值"""
        if key in self.return_value:
            return self.return_value[key]
        return []

    def get_return_value(self, key: str):
        """获取key的首个返回值"""
        if key in self.return_value:
            return self.return_value[key][0]
        return None

    def is_prevented_default(self):
        """是否阻止默认行为"""
        return self.is_prevent_default

    def is_prevented_postorder(self):
        """是否阻止后序插件执行"""
        return self.is_prevent_postorder

    def __init__(self, event: BaseEventModel):
        global global_eid_index
        eid = global_eid_index
        event = event
        event_name = event.__class__.__name__
        is_prevent_default = False
        is_prevent_postorder = False
        return_value: dict[str, list[Any]] = {}

        super().__init__(
            eid=eid,
            event_name=event_name,
            event=event,
            is_prevent_default=is_prevent_default,
            is_prevent_postorder=is_prevent_postorder,
            return_value=return_value,
        )

        global_eid_index += 1

    @classmethod
    def parse_from_dict(cls, data: dict[str, Any]) -> EventContext:
        event_name = data["event_name"]
        event_class = getattr(events_module, event_name)
        print(data['event'])
        event = event_class.model_validate(data["event"])

        inst = cls(
            event=event,
        )
        inst.eid = data["eid"]
        inst.is_prevent_default = data["is_prevent_default"]
        inst.is_prevent_postorder = data["is_prevent_postorder"]
        inst.return_value = data["return_value"]
        print(inst)
        return inst
    
    def update(
        self,
        **kwargs
    ):
        """更新事件上下文"""
        for key, value in kwargs.items():
            setattr(self, key, value)

    def model_dump(self, **kwargs):
        return {
            "eid": self.eid,
            "event_name": self.event_name,
            "event": self.event.model_dump(),
            "is_prevent_default": self.is_prevent_default,
            "is_prevent_postorder": self.is_prevent_postorder,
            "return_value": self.return_value,
        }