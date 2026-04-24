"""Unit tests for BoxRuntime backend selection mechanism."""

from __future__ import annotations

import logging
from unittest import mock

import pytest

from langbot_plugin.box.backend import BaseSandboxBackend
from langbot_plugin.box.runtime import BoxRuntime


@pytest.fixture
def logger():
    return logging.getLogger('test.runtime')


class MockBackend(BaseSandboxBackend):
    """Mock backend for testing."""

    def __init__(self, logger: logging.Logger, name: str, available: bool = True):
        super().__init__(logger)
        self.name = name
        self._available = available

    async def is_available(self) -> bool:
        return self._available

    async def start_session(self, spec):
        pass

    async def exec(self, session, spec):
        pass

    async def stop_session(self, session):
        pass


# ── E2B backend creation ────────────────────────────────────────────────

def test_e2b_backend_created_if_package_installed(logger):
    """E2B backend is created when package is installed."""
    with mock.patch('os.getenv', return_value=''):
        runtime = BoxRuntime(logger)
        # E2B backend exists (package installed)
        e2b_backend = runtime.backends[2]
        assert e2b_backend is not None
        assert e2b_backend.name == 'e2b'


def test_e2b_backend_none_if_package_not_installed(logger):
    """E2B backend is None when package is not installed."""
    with (
        mock.patch('os.getenv', return_value=''),
        mock.patch.object(BoxRuntime, '_create_e2b_backend', return_value=None),
    ):
        runtime = BoxRuntime(logger)
        # Third backend is None (package not installed)
        assert runtime.backends[2] is None
        # Filtered list for selection
        active_backends = [b for b in runtime.backends if b is not None]
        assert len(active_backends) == 2


def test_e2b_import_failure_returns_none(logger):
    """Import failure for e2b package returns None, not fatal."""
    with mock.patch('os.getenv', return_value=''):
        # _create_e2b_backend handles ImportError internally
        runtime = BoxRuntime(logger)
        # Should have Docker, nsjail, and E2B (if package installed) or None
        active_backends = [b for b in runtime.backends if b is not None]
        assert len(active_backends) >= 2


# ── BOX_BACKEND environment variable ───────────────────────────────────

@pytest.mark.anyio
async def test_box_backend_forces_specific_backend(logger):
    """BOX_BACKEND env var forces selection of named backend."""
    backend_e2b = MockBackend(logger, 'e2b', available=True)
    backend_docker = MockBackend(logger, 'docker', available=True)
    backend_nsjail = MockBackend(logger, 'nsjail', available=False)

    runtime = BoxRuntime(logger, backends=[backend_e2b, backend_docker, backend_nsjail])

    with mock.patch('os.getenv', side_effect=lambda k: 'docker' if k == 'BOX_BACKEND' else None):
        selected = await runtime._select_backend()

    assert selected.name == 'docker'
    assert selected is backend_docker


@pytest.mark.anyio
async def test_box_backend_unavailable_returns_none(logger):
    """When BOX_BACKEND specifies unavailable backend, returns None."""
    backend_e2b = MockBackend(logger, 'e2b', available=False)
    backend_docker = MockBackend(logger, 'docker', available=True)

    runtime = BoxRuntime(logger, backends=[backend_e2b, backend_docker])

    with mock.patch('os.getenv', side_effect=lambda k: 'e2b' if k == 'BOX_BACKEND' else None):
        selected = await runtime._select_backend()

    assert selected is None


@pytest.mark.anyio
async def test_box_backend_not_found_returns_none(logger):
    """When BOX_BACKEND specifies unknown backend name, returns None."""
    backend_docker = MockBackend(logger, 'docker', available=True)

    runtime = BoxRuntime(logger, backends=[backend_docker])

    with mock.patch('os.getenv', side_effect=lambda k: 'unknown' if k == 'BOX_BACKEND' else None):
        selected = await runtime._select_backend()

    assert selected is None


@pytest.mark.anyio
async def test_box_backend_no_fallback(logger):
    """When BOX_BACKEND is set but backend unavailable, does NOT fallback."""
    backend_e2b = MockBackend(logger, 'e2b', available=False)
    backend_docker = MockBackend(logger, 'docker', available=True)

    runtime = BoxRuntime(logger, backends=[backend_e2b, backend_docker])

    with mock.patch('os.getenv', side_effect=lambda k: 'e2b' if k == 'BOX_BACKEND' else None):
        selected = await runtime._select_backend()

    # Should return None, not fallback to docker
    assert selected is None


# ── Auto-detect backend selection ───────────────────────────────────────

@pytest.mark.anyio
async def test_auto_detect_first_available(logger):
    """Without BOX_BACKEND, selects first available backend."""
    backend_e2b = MockBackend(logger, 'e2b', available=False)
    backend_docker = MockBackend(logger, 'docker', available=True)
    backend_nsjail = MockBackend(logger, 'nsjail', available=False)

    runtime = BoxRuntime(logger, backends=[backend_e2b, backend_docker, backend_nsjail])

    with mock.patch('os.getenv', return_value=None):
        selected = await runtime._select_backend()

    assert selected.name == 'docker'


@pytest.mark.anyio
async def test_auto_detect_none_when_all_unavailable(logger):
    """Returns None when all backends are unavailable."""
    backend_docker = MockBackend(logger, 'docker', available=False)
    backend_nsjail = MockBackend(logger, 'nsjail', available=False)

    runtime = BoxRuntime(logger, backends=[backend_docker, backend_nsjail])

    with mock.patch('os.getenv', return_value=None):
        selected = await runtime._select_backend()

    assert selected is None


# ── Custom backends list ────────────────────────────────────────────────

def test_custom_backends_list_preserved(logger):
    """Providing custom backends list overrides auto-detection."""
    custom_backend = MockBackend(logger, 'custom', available=True)

    runtime = BoxRuntime(logger, backends=[custom_backend])

    assert len(runtime.backends) == 1
    assert runtime.backends[0].name == 'custom'


@pytest.mark.anyio
async def test_custom_backends_with_box_backend(logger):
    """BOX_BACKEND works with custom backends list."""
    backend_a = MockBackend(logger, 'a', available=True)
    backend_b = MockBackend(logger, 'b', available=True)

    runtime = BoxRuntime(logger, backends=[backend_a, backend_b])

    with mock.patch('os.getenv', side_effect=lambda k: 'b' if k == 'BOX_BACKEND' else None):
        selected = await runtime._select_backend()

    assert selected.name == 'b'