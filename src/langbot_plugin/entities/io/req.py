from __future__ import annotations

import pydantic
from typing import Any


class ActionRequest(pydantic.BaseModel):
    seq_id: int = pydantic.Field(..., description="The sequence id of the request")
    action: str
    data: dict[str, Any]

    @classmethod
    def make_request(
        cls, seq_id: int, action: str, data: dict[str, Any]
    ) -> ActionRequest:
        return cls(seq_id=seq_id, action=action, data=data)
