"""Localization support for LangBot Plugin CLI"""

from . import en_US, zh_Hans, zh_Hant, ja_JP

SUPPORTED_LOCALES = {
    "en_US": en_US.messages,
    "zh_Hans": zh_Hans.messages,
    "zh_Hant": zh_Hant.messages,
    "ja_JP": ja_JP.messages,
}


def get_locale_messages(locale: str) -> dict:
    """Get messages for a specific locale"""
    return SUPPORTED_LOCALES.get(locale, SUPPORTED_LOCALES["en_US"])
