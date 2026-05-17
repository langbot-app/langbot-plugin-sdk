"""BoxRuntimeClient abstraction for Box Runtime access."""

from __future__ import annotations

import abc
import logging
from typing import Any

from langbot_plugin.runtime.io.handler import Handler

from .actions import LangBotToBoxAction
from .errors import BoxError, BoxRuntimeUnavailableError
from .models import (
    BoxExecutionResult,
    BoxExecutionStatus,
    BoxManagedProcessInfo,
    BoxManagedProcessSpec,
    BoxSpec,
)


class BoxRuntimeClient(abc.ABC):
    """Abstract interface that BoxService uses to talk to a Box Runtime."""

    @abc.abstractmethod
    async def initialize(self) -> None: ...

    @abc.abstractmethod
    async def execute(self, spec: BoxSpec) -> BoxExecutionResult: ...

    @abc.abstractmethod
    async def shutdown(self) -> None: ...

    @abc.abstractmethod
    async def get_status(self) -> dict: ...

    @abc.abstractmethod
    async def get_sessions(self) -> list[dict]: ...

    @abc.abstractmethod
    async def get_backend_info(self) -> dict: ...

    @abc.abstractmethod
    async def delete_session(self, session_id: str) -> None: ...

    @abc.abstractmethod
    async def create_session(self, spec: BoxSpec) -> dict: ...

    @abc.abstractmethod
    async def start_managed_process(self, session_id: str, spec: BoxManagedProcessSpec) -> BoxManagedProcessInfo: ...

    @abc.abstractmethod
    async def get_managed_process(self, session_id: str, process_id: str = 'default') -> BoxManagedProcessInfo: ...

    @abc.abstractmethod
    async def get_session(self, session_id: str) -> dict: ...

    @abc.abstractmethod
    async def init(self, config: dict) -> None: ...

    async def list_skills(self) -> list[dict]:
        raise NotImplementedError

    async def get_skill(self, name: str) -> dict | None:
        raise NotImplementedError

    async def create_skill(self, skill: dict) -> dict:
        raise NotImplementedError

    async def update_skill(self, name: str, skill: dict) -> dict:
        raise NotImplementedError

    async def delete_skill(self, name: str) -> None:
        raise NotImplementedError

    async def scan_skill_directory(self, path: str) -> dict:
        raise NotImplementedError

    async def list_skill_files(
        self,
        name: str,
        path: str = '.',
        include_hidden: bool = False,
        max_entries: int = 200,
    ) -> dict:
        raise NotImplementedError

    async def read_skill_file(self, name: str, path: str) -> dict:
        raise NotImplementedError

    async def write_skill_file(self, name: str, path: str, content: str) -> dict:
        raise NotImplementedError

    async def preview_skill_zip(
        self,
        file_bytes: bytes,
        filename: str,
        source_subdir: str = '',
        target_suffix: str = 'upload',
    ) -> list[dict]:
        raise NotImplementedError

    async def install_skill_zip(
        self,
        file_bytes: bytes,
        filename: str,
        source_paths: list[str] | None = None,
        source_path: str = '',
        source_subdir: str = '',
        target_suffix: str = 'upload',
    ) -> list[dict]:
        raise NotImplementedError


def _translate_action_error(exc: Exception) -> BoxError:
    """Convert an ActionCallError message back into the appropriate BoxError subclass."""
    from .errors import (
        BoxBackendUnavailableError,
        BoxManagedProcessConflictError,
        BoxManagedProcessNotFoundError,
        BoxSessionConflictError,
        BoxSessionNotFoundError,
        BoxValidationError,
    )

    msg = str(exc)
    _ERROR_PREFIX_MAP: list[tuple[str, type[BoxError]]] = [
        ('BoxValidationError:', BoxValidationError),
        ('BoxSessionNotFoundError:', BoxSessionNotFoundError),
        ('BoxSessionConflictError:', BoxSessionConflictError),
        ('BoxManagedProcessNotFoundError:', BoxManagedProcessNotFoundError),
        ('BoxManagedProcessConflictError:', BoxManagedProcessConflictError),
        ('BoxBackendUnavailableError:', BoxBackendUnavailableError),
    ]
    for prefix, cls in _ERROR_PREFIX_MAP:
        if prefix in msg:
            return cls(msg)
    return BoxError(msg)


class ActionRPCBoxClient(BoxRuntimeClient):
    """Client that talks to BoxRuntime via the action RPC protocol."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._handler: Handler | None = None

    @property
    def handler(self) -> Handler:
        if self._handler is None:
            raise BoxRuntimeUnavailableError('box runtime not connected')
        return self._handler

    def set_handler(self, handler: Handler) -> None:
        self._handler = handler

    async def _call(self, action: LangBotToBoxAction, data: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
        try:
            return await self.handler.call_action(action, data, timeout=timeout)
        except BoxRuntimeUnavailableError:
            raise
        except Exception as exc:
            raise _translate_action_error(exc) from exc

    async def initialize(self) -> None:
        try:
            await self._call(LangBotToBoxAction.HEALTH, {})
            self._logger.info('LangBot Box runtime connected via action RPC.')
        except Exception as exc:
            raise BoxRuntimeUnavailableError(f'box runtime unavailable: {exc}') from exc

    async def execute(self, spec: BoxSpec) -> BoxExecutionResult:
        data = await self._call(LangBotToBoxAction.EXEC, spec.model_dump(mode='json'), timeout=300.0)
        return BoxExecutionResult(
            session_id=data['session_id'],
            backend_name=data['backend_name'],
            status=BoxExecutionStatus(data['status']),
            exit_code=data.get('exit_code'),
            stdout=data.get('stdout', ''),
            stderr=data.get('stderr', ''),
            duration_ms=data['duration_ms'],
        )

    async def shutdown(self) -> None:
        if self._handler is not None:
            try:
                await self._call(LangBotToBoxAction.SHUTDOWN, {})
            except Exception:
                pass
            self._handler = None

    async def get_status(self) -> dict:
        return await self._call(LangBotToBoxAction.STATUS, {})

    async def get_sessions(self) -> list[dict]:
        data = await self._call(LangBotToBoxAction.GET_SESSIONS, {})
        return data['sessions']

    async def get_session(self, session_id: str) -> dict:
        return await self._call(LangBotToBoxAction.GET_SESSION, {'session_id': session_id})

    async def get_backend_info(self) -> dict:
        return await self._call(LangBotToBoxAction.GET_BACKEND_INFO, {})

    async def delete_session(self, session_id: str) -> None:
        await self._call(LangBotToBoxAction.DELETE_SESSION, {'session_id': session_id}, timeout=30.0)

    async def create_session(self, spec: BoxSpec) -> dict:
        return await self._call(LangBotToBoxAction.CREATE_SESSION, spec.model_dump(mode='json'))

    async def start_managed_process(self, session_id: str, spec: BoxManagedProcessSpec) -> BoxManagedProcessInfo:
        data = await self._call(
            LangBotToBoxAction.START_MANAGED_PROCESS,
            {'session_id': session_id, 'spec': spec.model_dump(mode='json')},
        )
        return BoxManagedProcessInfo.model_validate(data)

    async def get_managed_process(self, session_id: str, process_id: str = 'default') -> BoxManagedProcessInfo:
        data = await self._call(LangBotToBoxAction.GET_MANAGED_PROCESS, {
            'session_id': session_id,
            'process_id': process_id,
        })
        return BoxManagedProcessInfo.model_validate(data)

    def get_managed_process_websocket_url(self, session_id: str, ws_relay_base_url: str, process_id: str = 'default') -> str:
        base = ws_relay_base_url
        if base.startswith('https://'):
            scheme = 'wss://'
            suffix = base[len('https://') :]
        elif base.startswith('http://'):
            scheme = 'ws://'
            suffix = base[len('http://') :]
        else:
            scheme = 'ws://'
            suffix = base
        return f'{scheme}{suffix}/v1/sessions/{session_id}/managed-process/{process_id}/ws'

    async def init(self, config: dict) -> None:
        await self._call(LangBotToBoxAction.INIT, config)

    async def list_skills(self) -> list[dict]:
        data = await self._call(LangBotToBoxAction.LIST_SKILLS, {})
        return data['skills']

    async def get_skill(self, name: str) -> dict | None:
        data = await self._call(LangBotToBoxAction.GET_SKILL, {'name': name})
        return data.get('skill')

    async def create_skill(self, skill: dict) -> dict:
        data = await self._call(LangBotToBoxAction.CREATE_SKILL, {'skill': skill})
        return data['skill']

    async def update_skill(self, name: str, skill: dict) -> dict:
        data = await self._call(LangBotToBoxAction.UPDATE_SKILL, {'name': name, 'skill': skill})
        return data['skill']

    async def delete_skill(self, name: str) -> None:
        await self._call(LangBotToBoxAction.DELETE_SKILL, {'name': name})

    async def scan_skill_directory(self, path: str) -> dict:
        return await self._call(LangBotToBoxAction.SCAN_SKILL_DIRECTORY, {'path': path})

    async def list_skill_files(
        self,
        name: str,
        path: str = '.',
        include_hidden: bool = False,
        max_entries: int = 200,
    ) -> dict:
        return await self._call(
            LangBotToBoxAction.LIST_SKILL_FILES,
            {
                'name': name,
                'path': path,
                'include_hidden': include_hidden,
                'max_entries': max_entries,
            },
        )

    async def read_skill_file(self, name: str, path: str) -> dict:
        return await self._call(LangBotToBoxAction.READ_SKILL_FILE, {'name': name, 'path': path})

    async def write_skill_file(self, name: str, path: str, content: str) -> dict:
        return await self._call(
            LangBotToBoxAction.WRITE_SKILL_FILE,
            {'name': name, 'path': path, 'content': content},
        )

    async def preview_skill_zip(
        self,
        file_bytes: bytes,
        filename: str,
        source_subdir: str = '',
        target_suffix: str = 'upload',
    ) -> list[dict]:
        file_key = await self.handler.send_file(file_bytes, 'zip')
        data = await self._call(
            LangBotToBoxAction.PREVIEW_SKILL_ZIP,
            {
                'file_key': file_key,
                'filename': filename,
                'source_subdir': source_subdir,
                'target_suffix': target_suffix,
            },
            timeout=60.0,
        )
        return data['skills']

    async def install_skill_zip(
        self,
        file_bytes: bytes,
        filename: str,
        source_paths: list[str] | None = None,
        source_path: str = '',
        source_subdir: str = '',
        target_suffix: str = 'upload',
    ) -> list[dict]:
        file_key = await self.handler.send_file(file_bytes, 'zip')
        data = await self._call(
            LangBotToBoxAction.INSTALL_SKILL_ZIP,
            {
                'file_key': file_key,
                'filename': filename,
                'source_paths': source_paths or [],
                'source_path': source_path,
                'source_subdir': source_subdir,
                'target_suffix': target_suffix,
            },
            timeout=120.0,
        )
        return data['skills']
