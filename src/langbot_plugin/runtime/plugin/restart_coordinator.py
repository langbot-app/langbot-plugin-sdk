from __future__ import annotations

import asyncio
import collections
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Callable

from langbot_plugin.entities.io.context import PluginWorkerPolicy


async def _complete_state_transition(operation: Awaitable[None]) -> None:
    """Finish one tiny coordinator mutation even if its caller is cancelled.

    A supervisor cancellation must not strand the circuit in half-open state.
    Shield the mutation and preserve the caller's cancellation after the
    coordinator lock has been released.
    """

    task = asyncio.create_task(operation)
    caller_cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            caller_cancelled = True
    task.result()
    if caller_cancelled:
        raise asyncio.CancelledError


@dataclass(slots=True)
class RestartPermit:
    """One globally admitted worker restart attempt.

    The launch slot is held only until the worker finishes registration.  A
    half-open probe remains logically owned until it survives the stable
    window, fails, or is abandoned by cancellation.
    """

    _coordinator: PluginRestartCoordinator
    is_half_open_probe: bool
    _launch_slot_held: bool = True
    _probe_active: bool = False

    def __post_init__(self) -> None:
        self._probe_active = self.is_half_open_probe

    def mark_ready(self) -> None:
        """Release scarce launch admission after successful initialization."""

        if not self._launch_slot_held:
            return
        self._launch_slot_held = False
        self._coordinator._release_launch_slot()

    async def mark_stable(self) -> None:
        """Close a half-open circuit after the probe remains healthy."""

        self.mark_ready()
        if not self._probe_active:
            return
        await _complete_state_transition(self._coordinator._record_probe_success())
        self._probe_active = False

    async def record_failure(self) -> None:
        """Record an unexpected exit and release every owned admission."""

        self.mark_ready()
        was_probe = self._probe_active
        if was_probe:
            await _complete_state_transition(
                self._coordinator._record_failure(was_probe=True)
            )
        else:
            await self._coordinator._record_failure(was_probe=False)
        self._probe_active = False

    async def abandon(self) -> None:
        """Release admission without treating intentional cancellation as failure."""

        self.mark_ready()
        if not self._probe_active:
            return
        await _complete_state_transition(self._coordinator._abandon_probe())
        self._probe_active = False


class PluginRestartCoordinator:
    """Bound concurrent launches and suppress cross-tenant restart storms."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._configured = False
        self._max_concurrent_restarts = 0
        self._failure_threshold = 0
        self._failure_window_seconds = 0.0
        self._circuit_open_seconds = 0.0
        self._launch_semaphore: asyncio.BoundedSemaphore | None = None
        self._state_lock = asyncio.Lock()
        self._state_changed = asyncio.Event()
        self._failure_times: collections.deque[float] = collections.deque()
        self._open_until = 0.0
        self._half_open_probe_inflight = False
        self._active_launches = 0
        self._gate_waiters = 0
        self._restart_attempts_total = 0
        self._restart_failures_total = 0
        self._circuit_open_total = 0

    def configure(self, policy: PluginWorkerPolicy) -> None:
        """Apply the immutable Runtime worker policy exactly once."""

        limits = (
            policy.max_concurrent_restarts,
            policy.restart_failure_threshold,
            float(policy.restart_failure_window_seconds),
            float(policy.restart_circuit_open_seconds),
        )
        if self._configured:
            current = (
                self._max_concurrent_restarts,
                self._failure_threshold,
                self._failure_window_seconds,
                self._circuit_open_seconds,
            )
            if current != limits:
                raise ValueError("Plugin restart policy cannot be changed at runtime")
            return

        self._max_concurrent_restarts = limits[0]
        self._failure_threshold = limits[1]
        self._failure_window_seconds = limits[2]
        self._circuit_open_seconds = limits[3]
        self._launch_semaphore = asyncio.BoundedSemaphore(self._max_concurrent_restarts)
        self._failure_times = collections.deque(maxlen=self._failure_threshold)
        self._configured = True

    def _require_configuration(self) -> asyncio.BoundedSemaphore:
        if not self._configured or self._launch_semaphore is None:
            raise RuntimeError("Plugin restart coordinator is not configured")
        return self._launch_semaphore

    def _trim_failures(self, now: float) -> None:
        cutoff = now - self._failure_window_seconds
        while self._failure_times and self._failure_times[0] < cutoff:
            self._failure_times.popleft()

    def _notify_state_change_locked(self) -> None:
        previous = self._state_changed
        self._state_changed = asyncio.Event()
        previous.set()

    def _release_launch_slot(self) -> None:
        semaphore = self._require_configuration()
        if self._active_launches <= 0:
            raise RuntimeError("Plugin restart launch admission underflow")
        self._active_launches -= 1
        semaphore.release()

    async def acquire(self) -> RestartPermit:
        """Wait for one launch slot and any active circuit-breaker gate."""

        semaphore = self._require_configuration()
        await semaphore.acquire()
        launch_slot_owned = True
        try:
            while True:
                wait_event: asyncio.Event | None = None
                wait_timeout: float | None = None
                async with self._state_lock:
                    now = self._clock()
                    self._trim_failures(now)
                    if self._open_until > now:
                        wait_event = self._state_changed
                        wait_timeout = self._open_until - now
                    elif self._open_until > 0:
                        if self._half_open_probe_inflight:
                            wait_event = self._state_changed
                        else:
                            self._half_open_probe_inflight = True
                            self._restart_attempts_total += 1
                            self._active_launches += 1
                            launch_slot_owned = False
                            return RestartPermit(self, is_half_open_probe=True)
                    else:
                        self._restart_attempts_total += 1
                        self._active_launches += 1
                        launch_slot_owned = False
                        return RestartPermit(self, is_half_open_probe=False)

                # Keep the semaphore slot while the circuit is unavailable.
                # At most max_concurrent_restarts tasks can therefore own a
                # cooldown timer or wake on a probe state change; all other
                # supervisors remain asleep in the semaphore FIFO.
                assert wait_event is not None
                self._gate_waiters += 1
                try:
                    if wait_timeout is None:
                        await wait_event.wait()
                    else:
                        try:
                            await asyncio.wait_for(
                                wait_event.wait(),
                                timeout=wait_timeout,
                            )
                        except asyncio.TimeoutError:
                            pass
                finally:
                    self._gate_waiters -= 1
        finally:
            if launch_slot_owned:
                semaphore.release()

    async def record_unadmitted_failure(self) -> None:
        """Count a failed initial launch before restart admission begins."""

        self._require_configuration()
        await self._record_failure(was_probe=False)

    async def _record_failure(self, *, was_probe: bool) -> None:
        async with self._state_lock:
            now = self._clock()
            self._trim_failures(now)
            self._failure_times.append(now)
            self._restart_failures_total += 1
            if was_probe:
                self._half_open_probe_inflight = False

            should_open = (
                was_probe
                or self._open_until > now
                or len(self._failure_times) >= self._failure_threshold
            )
            if should_open:
                was_open = self._open_until > now or self._half_open_probe_inflight
                self._open_until = max(
                    self._open_until,
                    now + self._circuit_open_seconds,
                )
                self._half_open_probe_inflight = False
                if not was_open:
                    self._circuit_open_total += 1
                self._notify_state_change_locked()

    async def _record_probe_success(self) -> None:
        async with self._state_lock:
            if not self._half_open_probe_inflight:
                return
            self._half_open_probe_inflight = False
            self._open_until = 0.0
            self._failure_times.clear()
            self._notify_state_change_locked()

    async def _abandon_probe(self) -> None:
        async with self._state_lock:
            if not self._half_open_probe_inflight:
                return
            self._half_open_probe_inflight = False
            self._notify_state_change_locked()

    def snapshot(self) -> dict[str, int | float | bool | str]:
        """Return O(1), identity-free health counters."""

        if not self._configured:
            return {"configured": False}
        now = self._clock()
        self._trim_failures(now)
        if self._open_until > now:
            state = "open"
        elif self._open_until > 0 or self._half_open_probe_inflight:
            state = "half_open"
        else:
            state = "closed"
        return {
            "configured": True,
            "state": state,
            "active_launches": self._active_launches,
            "gate_waiters": self._gate_waiters,
            "max_concurrent_restarts": self._max_concurrent_restarts,
            "failures_in_window": len(self._failure_times),
            "failure_threshold": self._failure_threshold,
            "open_remaining_seconds": max(self._open_until - now, 0.0),
            "half_open_probe_inflight": self._half_open_probe_inflight,
            "restart_attempts_total": self._restart_attempts_total,
            "restart_failures_total": self._restart_failures_total,
            "circuit_open_total": self._circuit_open_total,
        }
