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


class DependencyInstallError(Exception):
    """依赖安装失败"""

    def __init__(self, package: str, returncode: int, stderr: str):
        self.package = package
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"Failed to install {package}: {stderr}")

    def __str__(self):
        return f"Failed to install {self.package}: {self.stderr}"


class DependencyVerificationError(Exception):
    """依赖验证失败"""

    def __init__(self, missing: list[str], version_mismatch: list[str] = None):
        self.missing = missing
        self.version_mismatch = version_mismatch or []
        super().__init__(
            f"Missing dependencies: {missing}, Version mismatch: {self.version_mismatch}"
        )

    def __str__(self):
        return f"Missing dependencies: {self.missing}, Version mismatch: {self.version_mismatch}"


class ActionCallError(Exception):
    """The action call failed."""

    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return self.message
