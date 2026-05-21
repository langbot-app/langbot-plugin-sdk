"""
Workflow 通信协议实体模块

本模块定义了 Workflow 节点间通信的标准数据结构，与 Pipeline Query 兼容。
"""

from .enums import (
    ExecutionStatus,
    NodeStatus,
    TriggerType,
    LauncherType,
    PortType,
)
from .entities import (
    MessageContext,
    MessageEnvelope,
    NodeState,
    ExecutionStep,
    PortDefinition,
    ExecutionContext,
    NodeDefinition,
)

__all__ = [
    # Enums
    "ExecutionStatus",
    "NodeStatus",
    "TriggerType",
    "LauncherType",
    "PortType",
    # Entities
    "MessageContext",
    "MessageEnvelope",
    "NodeState",
    "ExecutionStep",
    "PortDefinition",
    "ExecutionContext",
    "NodeDefinition",
]
