from __future__ import annotations

import abc


class BaseComponent(abc.ABC):
    """The abstract base class for all components."""

    def __init__(self):
        pass

    @abc.abstractmethod
    def initialize(self) -> None:
        pass
