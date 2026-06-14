from __future__ import annotations

import datetime as dt
import enum
import ntpath
import posixpath

import pydantic


DEFAULT_BOX_IMAGE = 'rockchin/langbot-sandbox:latest'
DEFAULT_BOX_MOUNT_PATH = '/workspace'


class BoxNetworkMode(str, enum.Enum):
    OFF = 'off'
    ON = 'on'


class BoxExecutionStatus(str, enum.Enum):
    COMPLETED = 'completed'
    TIMED_OUT = 'timed_out'


class BoxHostMountMode(str, enum.Enum):
    NONE = 'none'
    READ_ONLY = 'ro'
    READ_WRITE = 'rw'


class BoxManagedProcessStatus(str, enum.Enum):
    RUNNING = 'running'
    EXITED = 'exited'


class BoxMountSpec(pydantic.BaseModel):
    """A single additional bind mount specification."""

    host_path: str
    mount_path: str
    mode: BoxHostMountMode = BoxHostMountMode.READ_WRITE

    @pydantic.field_validator('host_path')
    @classmethod
    def validate_host_path(cls, value: str) -> str:
        value = value.strip()
        if not (posixpath.isabs(value) or ntpath.isabs(value)):
            raise ValueError('host_path must be an absolute host path')
        return value

    @pydantic.field_validator('mount_path')
    @classmethod
    def validate_mount_path(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith('/'):
            raise ValueError('mount_path must be an absolute path inside the sandbox')
        return value


class BoxSpec(pydantic.BaseModel):
    cmd: str = ''
    workdir: str = DEFAULT_BOX_MOUNT_PATH
    timeout_sec: int = 30
    network: BoxNetworkMode = BoxNetworkMode.OFF
    session_id: str
    env: dict[str, str] = pydantic.Field(default_factory=dict)
    image: str = DEFAULT_BOX_IMAGE
    host_path: str | None = None
    host_path_mode: BoxHostMountMode = BoxHostMountMode.READ_WRITE
    mount_path: str = DEFAULT_BOX_MOUNT_PATH
    extra_mounts: list[BoxMountSpec] = pydantic.Field(default_factory=list)
    persistent: bool = False
    # Resource limits
    cpus: float = 1.0
    memory_mb: int = 512
    pids_limit: int = 128
    read_only_rootfs: bool = True
    workspace_quota_mb: int = 0

    @pydantic.model_validator(mode='before')
    @classmethod
    def populate_workdir_from_mount_path(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get('workdir') not in (None, ''):
            return data
        mount_path = data.get('mount_path')
        if isinstance(mount_path, str) and mount_path.strip():
            data = dict(data)
            data['workdir'] = mount_path
        return data

    @pydantic.field_validator('cmd')
    @classmethod
    def validate_cmd(cls, value: str) -> str:
        return value.strip()

    @pydantic.field_validator('workdir')
    @classmethod
    def validate_workdir(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith('/'):
            raise ValueError('workdir must be an absolute path inside the sandbox')
        return value

    @pydantic.field_validator('timeout_sec')
    @classmethod
    def validate_timeout_sec(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('timeout_sec must be greater than 0')
        return value

    @pydantic.field_validator('cpus')
    @classmethod
    def validate_cpus(cls, value: float) -> float:
        if value <= 0:
            raise ValueError('cpus must be greater than 0')
        return value

    @pydantic.field_validator('memory_mb')
    @classmethod
    def validate_memory_mb(cls, value: int) -> int:
        if value < 32:
            raise ValueError('memory_mb must be at least 32')
        return value

    @pydantic.field_validator('pids_limit')
    @classmethod
    def validate_pids_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError('pids_limit must be at least 1')
        return value

    @pydantic.field_validator('workspace_quota_mb')
    @classmethod
    def validate_workspace_quota_mb(cls, value: int) -> int:
        if value < 0:
            raise ValueError('workspace_quota_mb must be greater than or equal to 0')
        return value

    @pydantic.field_validator('session_id')
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('session_id must not be empty')
        return value

    @pydantic.field_validator('env')
    @classmethod
    def validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        return {str(k): str(v) for k, v in value.items()}

    @pydantic.field_validator('host_path')
    @classmethod
    def validate_host_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not (posixpath.isabs(value) or ntpath.isabs(value)):
            raise ValueError('host_path must be an absolute host path')
        return value

    @pydantic.field_validator('mount_path')
    @classmethod
    def validate_mount_path(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith('/'):
            raise ValueError('mount_path must be an absolute path inside the sandbox')
        return value

    @pydantic.model_validator(mode='after')
    def validate_host_mount_consistency(self) -> 'BoxSpec':
        if self.host_path is None:
            return self
        if self.host_path_mode == BoxHostMountMode.NONE:
            return self
        if self.workdir != self.mount_path and not self.workdir.startswith(f'{self.mount_path}/'):
            raise ValueError('workdir must stay under mount_path when host_path is provided')
        return self


class BoxProfile(pydantic.BaseModel):
    """Preset sandbox configuration.

    Provides default values for BoxSpec fields and optionally locks fields
    so that tool-call parameters cannot override them.
    """

    name: str
    image: str = DEFAULT_BOX_IMAGE
    network: BoxNetworkMode = BoxNetworkMode.OFF
    timeout_sec: int = 30
    host_path_mode: BoxHostMountMode = BoxHostMountMode.READ_WRITE
    max_timeout_sec: int = 120
    # Resource limits
    cpus: float = 1.0
    memory_mb: int = 512
    pids_limit: int = 128
    read_only_rootfs: bool = True
    workspace_quota_mb: int = 0
    locked: frozenset[str] = frozenset()

    model_config = pydantic.ConfigDict(frozen=True)


BUILTIN_PROFILES: dict[str, BoxProfile] = {
    'default': BoxProfile(
        name='default',
        network=BoxNetworkMode.OFF,
        host_path_mode=BoxHostMountMode.READ_WRITE,
        cpus=1.0,
        memory_mb=512,
        pids_limit=128,
        read_only_rootfs=True,
        max_timeout_sec=120,
    ),
    'offline_readonly': BoxProfile(
        name='offline_readonly',
        network=BoxNetworkMode.OFF,
        host_path_mode=BoxHostMountMode.READ_ONLY,
        cpus=0.5,
        memory_mb=256,
        pids_limit=64,
        read_only_rootfs=True,
        max_timeout_sec=60,
        locked=frozenset({'network', 'host_path_mode', 'read_only_rootfs'}),
    ),
    'network_basic': BoxProfile(
        name='network_basic',
        network=BoxNetworkMode.ON,
        host_path_mode=BoxHostMountMode.READ_WRITE,
        cpus=1.0,
        memory_mb=512,
        pids_limit=128,
        read_only_rootfs=True,
        max_timeout_sec=120,
    ),
    'network_extended': BoxProfile(
        name='network_extended',
        network=BoxNetworkMode.ON,
        host_path_mode=BoxHostMountMode.READ_WRITE,
        cpus=2.0,
        memory_mb=1024,
        pids_limit=256,
        read_only_rootfs=False,
        max_timeout_sec=300,
    ),
}


class BoxSessionInfo(pydantic.BaseModel):
    session_id: str
    backend_name: str
    backend_session_id: str
    image: str
    network: BoxNetworkMode
    host_path: str | None = None
    host_path_mode: BoxHostMountMode = BoxHostMountMode.READ_WRITE
    mount_path: str = DEFAULT_BOX_MOUNT_PATH
    persistent: bool = False
    cpus: float = 1.0
    memory_mb: int = 512
    pids_limit: int = 128
    read_only_rootfs: bool = True
    workspace_quota_mb: int = 0
    created_at: dt.datetime
    last_used_at: dt.datetime


class BoxManagedProcessSpec(pydantic.BaseModel):
    process_id: str = 'default'
    command: str
    args: list[str] = pydantic.Field(default_factory=list)
    env: dict[str, str] = pydantic.Field(default_factory=dict)
    cwd: str = DEFAULT_BOX_MOUNT_PATH

    @pydantic.field_validator('command')
    @classmethod
    def validate_command(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('command must not be empty')
        return value

    @pydantic.field_validator('args')
    @classmethod
    def validate_args(cls, value: list[str]) -> list[str]:
        return [str(item) for item in value]

    @pydantic.field_validator('env')
    @classmethod
    def validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        return {str(k): str(v) for k, v in value.items()}

    @pydantic.field_validator('cwd')
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith('/'):
            raise ValueError('cwd must be an absolute path inside the sandbox')
        return value


class BoxManagedProcessInfo(pydantic.BaseModel):
    session_id: str
    process_id: str = 'default'
    status: BoxManagedProcessStatus
    command: str
    args: list[str]
    cwd: str
    env_keys: list[str]
    attached: bool = False
    started_at: dt.datetime
    exited_at: dt.datetime | None = None
    exit_code: int | None = None
    stderr_preview: str = ''


class BoxExecutionResult(pydantic.BaseModel):
    session_id: str
    backend_name: str
    status: BoxExecutionStatus
    exit_code: int | None
    stdout: str = ''
    stderr: str = ''
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.status == BoxExecutionStatus.COMPLETED and self.exit_code == 0
