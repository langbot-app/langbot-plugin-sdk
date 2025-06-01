from __future__ import annotations

import pydantic
from typing import Any, Optional


class ActionResponse(pydantic.BaseModel):
    seq_id: Optional[int] = None
    code: int = pydantic.Field(..., description="The code of the response")
    message: str = pydantic.Field(..., description="The message of the response")
    data: dict[str, Any] = pydantic.Field(..., description="The data of the response")

    @classmethod
    def success(cls, data: dict[str, Any]) -> ActionResponse:
        return cls(seq_id=0, code=0, message="success", data=data)

    @classmethod
    def error(cls, message: str) -> ActionResponse:
        return cls(code=1, message=message, data={})
