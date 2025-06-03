from __future__ import annotations

import typing

from langbot_plugin.api.definition.components.base import BaseComponent
from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.api.entities.builtin.platform import events as platform_events


class MessagePlatformAdapter(BaseComponent):
    """消息平台适配器基类"""

    name: str

    bot_account_id: int
    """机器人账号ID，需要在初始化时设置"""

    config: dict

    logger: EventLogger

    def __init__(self, config: dict, logger: EventLogger):
        """初始化适配器

        Args:
            config (dict): 对应的配置
            logger (EventLogger): 事件日志记录器
        """
        self.config = config
        self.logger = logger

    async def send_message(self, target_type: str, target_id: str, message: platform_message.MessageChain):
        """主动发送消息

        Args:
            target_type (str): 目标类型，`person`或`group`
            target_id (str): 目标ID
            message (platform.types.MessageChain): 消息链
        """
        raise NotImplementedError

    async def reply_message(
        self,
        message_source: platform_events.MessageEvent,
        message: platform_message.MessageChain,
        quote_origin: bool = False,
    ):
        """回复消息

        Args:
            message_source (platform.types.MessageEvent): 消息源事件
            message (platform.types.MessageChain): 消息链
            quote_origin (bool, optional): 是否引用原消息. Defaults to False.
        """
        raise NotImplementedError

    async def is_muted(self, group_id: int) -> bool:
        """获取账号是否在指定群被禁言"""
        raise NotImplementedError

    def register_listener(
        self,
        event_type: typing.Type[platform_events.Event],
        callback: typing.Callable[[platform_events.Event, MessagePlatformAdapter], None],
    ):
        """注册事件监听器

        Args:
            event_type (typing.Type[platform.types.Event]): 事件类型
            callback (typing.Callable[[platform.types.Event], None]): 回调函数，接收一个参数，为事件
        """
        raise NotImplementedError

    def unregister_listener(
        self,
        event_type: typing.Type[platform_events.Event],
        callback: typing.Callable[[platform_events.Event, MessagePlatformAdapter], None],
    ):
        """注销事件监听器

        Args:
            event_type (typing.Type[platform.types.Event]): 事件类型
            callback (typing.Callable[[platform.types.Event], None]): 回调函数，接收一个参数，为事件
        """
        raise NotImplementedError

    async def run_async(self):
        """异步运行"""
        raise NotImplementedError

    async def kill(self) -> bool:
        """关闭适配器

        Returns:
            bool: 是否成功关闭，热重载时若此函数返回False则不会重载MessageSource底层
        """
        raise NotImplementedError


class MessageConverter:
    """消息链转换器基类"""

    @staticmethod
    def yiri2target(message_chain: platform_message.MessageChain):
        """将源平台消息链转换为目标平台消息链

        Args:
            message_chain (platform.types.MessageChain): 源平台消息链

        Returns:
            typing.Any: 目标平台消息链
        """
        raise NotImplementedError

    @staticmethod
    def target2yiri(message_chain: typing.Any) -> platform_message.MessageChain:
        """将目标平台消息链转换为源平台消息链

        Args:
            message_chain (typing.Any): 目标平台消息链

        Returns:
            platform.types.MessageChain: 源平台消息链
        """
        raise NotImplementedError


class EventConverter:
    """事件转换器基类"""

    @staticmethod
    def yiri2target(event: typing.Type[platform_events.Event]):
        """将源平台事件转换为目标平台事件

        Args:
            event (typing.Type[platform.types.Event]): 源平台事件

        Returns:
            typing.Any: 目标平台事件
        """
        raise NotImplementedError

    @staticmethod
    def target2yiri(event: typing.Any) -> platform_events.Event:
        """将目标平台事件的调用参数转换为源平台的事件参数对象

        Args:
            event (typing.Any): 目标平台事件

        Returns:
            typing.Type[platform.types.Event]: 源平台事件
        """
        raise NotImplementedError
