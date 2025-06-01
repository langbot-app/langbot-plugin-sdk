# Plugin runtime container

from __future__ import annotations


class PluginContainer:
    """The container for plugins."""

    def __init__(self):
        self.plugins = {}
        