import pydantic

class CommandError(pydantic.BaseModel):

    message: str

    def __init__(self, message: str):
        
        super().__init__(message=message)

    def __str__(self):
        return self.message


class CommandNotFoundError(CommandError):
    def __init__(self, message: str | None = None):
        super().__init__("未知命令: " + (message or ""))


class CommandPrivilegeError(CommandError):
    def __init__(self, message: str | None = None):
        super().__init__("权限不足: " + (message or ""))


class ParamNotEnoughError(CommandError):
    def __init__(self, message: str | None = None):
        super().__init__("参数不足: " + (message or ""))


class CommandOperationError(CommandError):
    def __init__(self, message: str | None = None):
        super().__init__("操作失败: " + (message or ""))
