"""Regression: a stuck synchronous vendor must not pin asyncio's executor."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("plugin", ["dashscope-agent", "tbox-agent"])
@pytest.mark.parametrize("operation", ["timeout", "cancel"])
def test_stuck_vendor_stream_does_not_block_event_loop_shutdown(plugin, operation):
    client_module = "dashscope_client" if plugin == "dashscope-agent" else "tbox_client"
    code = f"""
import asyncio
import threading
from pkg.{client_module} import _iterate_sync_in_thread

def stuck_vendor_fixture():
    threading.Event().wait(60)
    yield {{}}

async def main():
    stream = _iterate_sync_in_thread(stuck_vendor_fixture, timeout={0.05 if operation == "timeout" else 120})
    task = asyncio.create_task(anext(stream))
    if {operation == "cancel"}:
        await asyncio.sleep(0.05)
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        assert {operation == "cancel"}
    except Exception as exc:
        assert {operation == "timeout"}
        assert isinstance(exc, TimeoutError) or getattr(exc, 'code', '') == 'dashscope.timeout', repr(exc)
    else:
        raise AssertionError('stalled fixture unexpectedly yielded')
    await stream.aclose()

asyncio.run(main())
print('EXECUTOR_SHUTDOWN_OK')
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT / plugin, text=True, capture_output=True, timeout=3
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Vendor stream left a blocking executor queue.get; asyncio.run cannot shut down")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EXECUTOR_SHUTDOWN_OK" in result.stdout
