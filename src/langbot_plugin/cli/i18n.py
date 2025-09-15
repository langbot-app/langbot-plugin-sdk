from __future__ import annotations

import locale
import os
from typing import Dict, Any

from .locales import get_locale_messages, SUPPORTED_LOCALES


class I18nManager:
    """国际化管理器 / Internationalization Manager"""

    def __init__(self):
        self._current_locale = self._detect_locale()
        self._messages = get_locale_messages(self._current_locale)

    def _detect_locale(self) -> str:
        """检测系统语言环境 / Detect system locale"""
        # 检查环境变量
        lang = os.environ.get("LANG", "")
        lc_all = os.environ.get("LC_ALL", "")
        lc_messages = os.environ.get("LC_MESSAGES", "")

        # 优先级：LC_ALL > LC_MESSAGES > LANG
        locale_str = lc_all or lc_messages or lang

        # 如果环境变量没有设置，使用系统locale
        if not locale_str:
            try:
                locale_str = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
            except:
                locale_str = ""

        # 根据locale字符串判断语言
        if locale_str:
            locale_lower = locale_str.lower()
            if "zh" in locale_lower and (
                "cn" in locale_lower or "hans" in locale_lower
            ):
                return "zh_Hans"
            elif "zh" in locale_lower and (
                "tw" in locale_lower
                or "hk" in locale_lower
                or "mo" in locale_lower
                or "hant" in locale_lower
            ):
                return "zh_Hant"
            elif locale_lower.startswith("ja") or "japan" in locale_lower:
                return "ja_JP"
            elif locale_lower.startswith("en"):
                return "en_US"

        # 默认返回英文
        return "en_US"

    def get_message(self, key: str, *args) -> str:
        """获取本地化消息 / Get localized message"""
        message = self._messages.get(key, key)

        if args:
            try:
                return message.format(*args)
            except:
                return message
        return message

    def set_locale(self, locale: str) -> None:
        """设置语言环境 / Set locale"""
        if locale in SUPPORTED_LOCALES:
            self._current_locale = locale
            self._messages = get_locale_messages(locale)

    def get_current_locale(self) -> str:
        """获取当前语言环境 / Get current locale"""
        return self._current_locale


# 全局i18n管理器实例
_i18n_manager = I18nManager()


def t(key: str, *args) -> str:
    """翻译函数快捷方式 / Translation function shortcut"""
    return _i18n_manager.get_message(key, *args)


def set_locale(locale: str) -> None:
    """设置语言环境快捷方式 / Set locale shortcut"""
    _i18n_manager.set_locale(locale)


def get_current_locale() -> str:
    """获取当前语言环境快捷方式 / Get current locale shortcut"""
    return _i18n_manager.get_current_locale()


def extract_i18n_label(labels: dict[str, str]) -> str:
    """提取i18n标签 / Extract i18n label"""

    if get_current_locale() in labels:
        return labels[get_current_locale()]
    else:
        return labels["en_US"]


def cli_print(key: str, *args) -> None:
    """CLI打印函数，只输出单一语言 / CLI print function, outputs single language only"""
    print(t(key, *args))
