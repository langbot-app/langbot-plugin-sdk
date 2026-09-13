"""Regression tests for local run controls, using genuine SDK contexts."""

from __future__ import annotations

import asyncio

import pytest

from components.runner.default import RunDeadline, RunInterruptChecker
from tests.test_runner import make_context


@pytest.mark.asyncio
async def test_operation_timeout_is_not_mistaken_for_poll_timeout():
    checker = RunInterruptChecker(None, make_context())
    operation_error = asyncio.TimeoutError("operation itself timed out")

    async def operation():
        raise operation_error

    with pytest.raises(asyncio.TimeoutError) as caught:
        await checker.wait_for(operation(), deadline=RunDeadline(0.02))

    assert caught.value is operation_error


@pytest.mark.asyncio
async def test_operation_timeout_propagates_without_deadline_when_polling():
    class RunLedgerFixture:
        async def run_get(self, run_id):
            # Give the enclosing test timeout a chance to stop a regression loop.
            await asyncio.sleep(0)
            return {"run_id": run_id, "status": "running"}

    context = make_context()
    context.context.available_apis.run_get = True
    checker = RunInterruptChecker(RunLedgerFixture(), context)
    operation_error = asyncio.TimeoutError("operation itself timed out")

    async def operation():
        raise operation_error

    with pytest.raises(asyncio.TimeoutError) as caught:
        await asyncio.wait_for(checker.wait_for(operation()), timeout=0.25)

    assert caught.value is operation_error
