from __future__ import annotations


class ConnectionClosedError(Exception):
    """The connection is closed."""

    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return self.message


class ActionCallTimeoutError(Exception):
    """The action call timed out."""

    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return self.message


class ActionCallError(Exception):
    """The action call failed."""

    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return self.message
