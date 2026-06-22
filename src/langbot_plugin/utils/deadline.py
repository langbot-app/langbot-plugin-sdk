from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator, TypeVar

_T = TypeVar("_T")


def remaining_deadline_seconds(deadline_at: Any) -> float | None:
    """Return seconds until a Unix deadline timestamp, or None if absent/invalid."""
    if deadline_at is None:
        return None
    try:
        return float(deadline_at) - time.time()
    except (TypeError, ValueError):
        return None


async def anext_with_deadline(
    gen: AsyncGenerator[_T, None],
    deadline_at: Any,
) -> _T:
    """Return the next item from an async generator before the deadline expires."""
    remaining = remaining_deadline_seconds(deadline_at)
    if remaining is not None and remaining <= 0:
        await gen.aclose()
        raise asyncio.TimeoutError

    try:
        if remaining is None:
            return await anext(gen)
        return await asyncio.wait_for(anext(gen), timeout=remaining)
    except asyncio.TimeoutError:
        await gen.aclose()
        raise
