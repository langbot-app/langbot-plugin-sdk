from __future__ import annotations

import abc


class CLICommand(abc.ABC):
    @abc.abstractmethod
    def run(self):
        pass
