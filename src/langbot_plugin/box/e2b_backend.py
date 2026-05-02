from __future__ import annotations

import datetime as dt
import json
import logging
import os

from .backend import BaseSandboxBackend, _MAX_RAW_OUTPUT_BYTES
from .errors import BoxError
from .models import (
    BoxExecutionResult,
    BoxExecutionStatus,
    BoxHostMountMode,
    BoxNetworkMode,
    BoxSessionInfo,
    BoxSpec,
)
from .security import validate_sandbox_security

# E2B sandbox uses /home/user as the default writable directory
# We map /workspace to /home/user/workspace for compatibility
E2B_DEFAULT_WORKDIR = '/home/user'
E2B_WORKSPACE_DIR = '/home/user/workspace'

# Lazy imports for e2b - only imported when actually needed
_e2b_available: bool | None = None
_AsyncSandbox = None
_CommandResult = None


def _check_e2b_available(force: bool = False) -> bool:
    """Check if e2b package is available (cached result).

    Args:
        force: If True, re-check even if cached result exists.
    """
    global _e2b_available, _AsyncSandbox, _CommandResult
    if _e2b_available is not None and not force:
        return _e2b_available

    try:
        from e2b import AsyncSandbox, CommandResult

        _AsyncSandbox = AsyncSandbox
        _CommandResult = CommandResult
        _e2b_available = True
    except ImportError:
        _e2b_available = False

    return _e2b_available


def _reset_e2b_cache() -> None:
    """Reset the e2b availability cache, forcing re-check on next call."""
    global _e2b_available, _AsyncSandbox, _CommandResult
    _e2b_available = None
    _AsyncSandbox = None
    _CommandResult = None


def _adapt_path_for_e2b(path: str) -> str:
    """Adapt paths for E2B sandbox environment.

    E2B sandbox doesn't have /workspace by default, so we map it to
    /home/user/workspace which is writable.
    """
    if path == '/workspace' or path.startswith('/workspace/'):
        return path.replace('/workspace', E2B_WORKSPACE_DIR, 1)
    return path


class E2BSandboxBackend(BaseSandboxBackend):
    """E2B/CubeSandbox sandbox backend.

    Supports both E2B cloud service and self-hosted CubeSandbox.
    Configuration sources (priority from high to low):
    1. Environment variables: E2B_API_KEY, E2B_API_URL
    2. Configuration passed via configure() method (from LangBot config.yaml)
    """

    name = 'e2b'

    def __init__(self, logger: logging.Logger):
        super().__init__(logger)
        self._api_key: str | None = None
        self._api_url: str | None = None
        self._template: str | None = None
        self._config_from_langbot: dict = {}

    def configure(self, config: dict) -> None:
        """Apply configuration from LangBot config.yaml.

        Environment variables take precedence over config.yaml values.
        """
        self._config_from_langbot = config
        # Reset cache to force re-check if e2b package was installed later
        _reset_e2b_cache()

    async def initialize(self):
        """Load configuration from environment variables (priority) or config.yaml."""
        # Environment variables take precedence
        self._api_key = os.getenv('E2B_API_KEY') or self._config_from_langbot.get('api_key')
        self._api_url = os.getenv('E2B_API_URL') or self._config_from_langbot.get('api_url')
        self._template = self._config_from_langbot.get('template')

    async def is_available(self) -> bool:
        """Check if E2B backend is available.

        Returns True if:
        1. e2b package is installed
        2. E2B_API_KEY environment variable is set
        """
        if not _check_e2b_available():
            self.logger.info('e2b package not installed')
            return False

        if not self._api_key:
            self.logger.info('E2B_API_KEY not set')
            return False

        return True

    async def start_session(self, spec: BoxSpec) -> BoxSessionInfo:
        """Create a new E2B sandbox session.

        Maps BoxSpec fields to AsyncSandbox.create() parameters:
        - template: spec.image (E2B template ID)
        - envs: spec.env
        - timeout: sandbox lifetime timeout (not command timeout)
        - metadata: CubeSandbox host-mount configuration
        """
        validate_sandbox_security(spec)

        if not _check_e2b_available():
            raise BoxError('e2b package not installed')

        now = dt.datetime.now(dt.timezone.utc)

        # Adapt paths for E2B environment
        workdir = _adapt_path_for_e2b(spec.workdir)
        mount_path = _adapt_path_for_e2b(spec.mount_path)

        # Build create parameters
        create_kwargs = {}

        # Template - use spec.image if provided, otherwise configured template, otherwise E2B default
        if spec.image and spec.image != 'rockchin/langbot-sandbox:latest':
            create_kwargs['template'] = spec.image
        elif self._template:
            create_kwargs['template'] = self._template

        # Environment variables
        if spec.env:
            create_kwargs['envs'] = spec.env

        # API key and domain (for CubeSandbox self-deployment)
        if self._api_key:
            create_kwargs['api_key'] = self._api_key
        if self._api_url:
            # E2B SDK uses 'domain' for self-hosted API URL
            create_kwargs['domain'] = self._api_url

        # Build metadata for CubeSandbox host-mount
        metadata = {}
        if spec.host_path and spec.host_path_mode != BoxHostMountMode.NONE:
            metadata['host-mount'] = json.dumps([{
                'hostPath': spec.host_path,
                'mountPath': mount_path,
                'readOnly': spec.host_path_mode == BoxHostMountMode.READ_ONLY,
            }])
        if metadata:
            create_kwargs['metadata'] = metadata

        # Network mode - E2B uses allow_internet_access parameter
        # Note: E2B SDK doesn't have this directly in create(), but CubeSandbox may support it
        # For now, we rely on template configuration for network access

        self.logger.info(
            f'LangBot Box backend start_session: backend=e2b '
            f'session_id={spec.session_id} '
            f'template={create_kwargs.get("template", "default")} '
            f'network={spec.network.value} '
            f'host_path={spec.host_path} host_path_mode={spec.host_path_mode.value} mount_path={mount_path} '
            f'env_keys={sorted(spec.env.keys())}'
        )

        try:
            sandbox = await _AsyncSandbox.create(**create_kwargs)
        except Exception as exc:
            raise BoxError(f'Failed to create E2B sandbox: {exc}')

        return BoxSessionInfo(
            session_id=spec.session_id,
            backend_name=self.name,
            backend_session_id=sandbox.sandbox_id,
            image=spec.image,
            network=spec.network,
            host_path=spec.host_path,
            host_path_mode=spec.host_path_mode,
            mount_path=mount_path,
            persistent=spec.persistent,
            cpus=spec.cpus,
            memory_mb=spec.memory_mb,
            pids_limit=spec.pids_limit,
            read_only_rootfs=spec.read_only_rootfs,
            workspace_quota_mb=spec.workspace_quota_mb,
            created_at=now,
            last_used_at=now,
        )

    async def exec(self, session: BoxSessionInfo, spec: BoxSpec) -> BoxExecutionResult:
        """Execute a command in the E2B sandbox.

        Reconnects to existing sandbox via AsyncSandbox.connect() and runs command.
        """
        if not _check_e2b_available():
            raise BoxError('e2b package not installed')

        start = dt.datetime.now(dt.timezone.utc)

        # Connect kwargs
        connect_kwargs = {}
        if self._api_key:
            connect_kwargs['api_key'] = self._api_key
        if self._api_url:
            connect_kwargs['domain'] = self._api_url

        # Adapt workdir for E2B environment (use session's mount_path as base)
        workdir = _adapt_path_for_e2b(spec.workdir)

        cmd_preview = spec.cmd.strip()
        if len(cmd_preview) > 400:
            cmd_preview = f'{cmd_preview[:397]}...'
        self.logger.info(
            f'LangBot Box backend exec: backend=e2b '
            f'session_id={session.session_id} sandbox_id={session.backend_session_id} '
            f'workdir={workdir} timeout_sec={spec.timeout_sec} '
            f'env_keys={sorted(spec.env.keys())} cmd={cmd_preview}'
        )

        try:
            sandbox = await _AsyncSandbox.connect(
                sandbox_id=session.backend_session_id,
                **connect_kwargs
            )
        except Exception as exc:
            raise BoxError(f'Failed to connect to E2B sandbox: {exc}')

        # Run the command
        # Note: E2B requires workdir to exist before running command
        # We create it as part of the command, not via cwd parameter
        run_kwargs = {
            'cmd': f'mkdir -p {workdir} && cd {workdir} && {spec.cmd}',
            'timeout': spec.timeout_sec,
        }
        if spec.env:
            run_kwargs['envs'] = spec.env

        try:
            result = await sandbox.commands.run(**run_kwargs)
        except Exception as exc:
            # Check if it's a timeout
            duration_ms = int((dt.datetime.now(dt.timezone.utc) - start).total_seconds() * 1000)
            error_msg = str(exc)
            if 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                return BoxExecutionResult(
                    session_id=session.session_id,
                    backend_name=self.name,
                    status=BoxExecutionStatus.TIMED_OUT,
                    exit_code=None,
                    stdout='',
                    stderr=f'Command timed out after {spec.timeout_sec} seconds.',
                    duration_ms=duration_ms,
                )
            raise BoxError(f'E2B command execution failed: {exc}')

        duration_ms = int((dt.datetime.now(dt.timezone.utc) - start).total_seconds() * 1000)

        # Process output - apply truncation if needed
        stdout = self._truncate_output(result.stdout or '')
        stderr = self._truncate_output(result.stderr or '')

        return BoxExecutionResult(
            session_id=session.session_id,
            backend_name=self.name,
            status=BoxExecutionStatus.COMPLETED,
            exit_code=result.exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    async def stop_session(self, session: BoxSessionInfo):
        """Kill the E2B sandbox."""
        self.logger.info(
            f'LangBot Box backend stop_session: backend=e2b '
            f'session_id={session.session_id} sandbox_id={session.backend_session_id}'
        )

        if not _check_e2b_available():
            return  # Nothing to do if package not available

        try:
            await _AsyncSandbox.kill(
                sandbox_id=session.backend_session_id,
                api_key=self._api_key,
                domain=self._api_url,
            )
        except Exception as exc:
            self.logger.warning(f'Failed to kill E2B sandbox: {exc}')

    def _truncate_output(self, output: str, limit: int = _MAX_RAW_OUTPUT_BYTES) -> str:
        """Truncate output if exceeds the limit."""
        if len(output.encode('utf-8', errors='replace')) > limit:
            # Truncate to approximately the limit
            truncated = output[:limit]
            truncated += f'\n... [output clipped at {limit} bytes]'
            return truncated
        return output