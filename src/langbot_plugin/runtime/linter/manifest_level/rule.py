from __future__ import annotations

import abc
import enum
import pydantic
import typing


from langbot_plugin.cli.i18n import I18nMessage


class ResultLevel(enum.Enum):
    """Result level"""

    ERROR = "error"
    """Error"""
    WARNING = "warning"
    """Warning"""
    SUGGESTION = "suggestion"
    """Suggestion"""


class ManifestLevelRuleResult(pydantic.BaseModel):
    """Manifest level rule result"""

    level: ResultLevel

class ManifestLevelRule(abc.ABC):
    """Manifest level rule interface"""

    @abc.abstractmethod
    def check(self, manifest: typing.Dict[str, typing.Any]) -> list[str]:
        """Check if the manifest is valid"""
        return []