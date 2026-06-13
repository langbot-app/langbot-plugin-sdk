from __future__ import annotations

import time

import pytest

from langbot_plugin.utils import deadline


async def _empty_generator():
    if False:
        yield None


@pytest.mark.anyio
async def test_anext_with_deadline_preserves_natural_exhaustion_after_deadline(monkeypatch):
    """A naturally exhausted generator must not be reported as a timeout."""
    now = time.time()
    ticks = iter([now, now + 2])
    monkeypatch.setattr(deadline.time, "time", lambda: next(ticks, now + 2))

    with pytest.raises(StopAsyncIteration):
        await deadline.anext_with_deadline(_empty_generator(), now + 1)
