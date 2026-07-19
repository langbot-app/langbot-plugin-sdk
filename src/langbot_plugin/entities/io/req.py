from __future__ import annotations

import pydantic
from typing import Any

from langbot_plugin.entities.io.context import ActionContext


class ActionRequest(pydantic.BaseModel):
    seq_id: int = pydantic.Field(..., description="The sequence id of the request")
    action: str
    data: dict[str, Any]
    context: ActionContext | None = None

    @classmethod
    def make_request(
        cls,
        seq_id: int,
        action: str,
        data: dict[str, Any],
        context: ActionContext | dict[str, Any] | None = None,
    ) -> ActionRequest:
        return cls(seq_id=seq_id, action=action, data=data, context=context)

    def model_dump(self, **kwargs):
        # Preserve the exact legacy wire shape when no Workspace context is
        # present, while serializing the context envelope for new peers.
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(**kwargs)
