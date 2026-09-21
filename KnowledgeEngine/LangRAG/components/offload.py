"""Bound CPU/file parsing work per installation, including cancelled callers."""
import asyncio
from components.shared_state import settle


class BoundedOffload:
    def __init__(self, concurrency=2):
        self._slots = asyncio.Semaphore(concurrency)

    async def run(self, function, *args, **kwargs):
        async with self._slots:
            # Cancellation cannot terminate a Python thread. Keep its slot until
            # completion; never launch replacement work beyond the bound.
            return await settle(asyncio.create_task(asyncio.to_thread(function, *args, **kwargs)))
