"""Workflow 与 Pipeline 兼容性转换函数

本模块提供 MessageEnvelope 与 Pipeline Query 之间的双向转换，
确保 Workflow 可以无缝调用 Pipeline，同时保持完整的上下文信息。
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from .entities import (
    MessageEnvelope,
    ExecutionContext,
    MessageContext,
)
from .enums import ExecutionStatus


def envelope_to_query(
    envelope: MessageEnvelope,
    query_class: Any,
) -> Any:
    """将 MessageEnvelope 转换为 Pipeline Query 对象
    
    Args:
        envelope: Workflow 消息信封
        query_class: Pipeline Query 类（动态导入以避免循环依赖）
    
    Returns:
        Pipeline Query 对象
    
    Example:
        >>> from langbot_plugin.api.entities.builtin.pipeline import Query
        >>> envelope = MessageEnvelope(
        ...     message_id="msg_123",
        ...     message_content="Hello",
        ...     sender_id="user_456",
        ... )
        >>> query = envelope_to_query(envelope, Query)
    """
    # 构建消息事件对象
    message_event = _build_message_event(envelope)
    
    # 构建消息链
    message_chain = _build_message_chain(envelope)
    
    # 构建变量字典，标记来自 Workflow
    variables = {
        '_called_from_workflow': True,
        '_workflow_execution_id': envelope.execution_id,
        '_workflow_id': envelope.workflow_id,
        **(envelope.variables or {}),
    }
    
    # 创建 Query 对象
    query = query_class(
        bot_uuid=envelope.bot_id,
        query_id=-1,  # 特殊标记：来自 Workflow
        launcher_type=envelope.launcher_type,
        launcher_id=envelope.launcher_id,
        sender_id=envelope.sender_id,
        message_event=message_event,
        message_chain=message_chain,
        variables=variables,
        resp_messages=[],
        resp_message_chain=[],
        pipeline_uuid=envelope.workflow_id,
    )
    
    return query


def query_to_envelope(
    query: Any,
    execution_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
) -> MessageEnvelope:
    """将 Pipeline Query 转换为 MessageEnvelope
    
    Args:
        query: Pipeline Query 对象
        execution_id: 执行 ID（可选，如果不提供则从 query 中提取）
        workflow_id: 工作流 ID（可选，如果不提供则从 query 中提取）
    
    Returns:
        MessageEnvelope 对象
    
    Example:
        >>> envelope = query_to_envelope(query, execution_id="exec_123")
    """
    # 提取响应文本
    response_text = _extract_response_text(query)
    
    # 提取响应消息链
    response_chain = _extract_response_chain(query)
    
    # 确定执行 ID 和工作流 ID
    final_execution_id = execution_id or str(getattr(query, 'query_id', ''))
    final_workflow_id = workflow_id or getattr(query, 'pipeline_uuid', '')
    
    # 确定状态
    status = 'error' if query.variables.get('_monitoring_has_error') else 'success'
    
    # 创建 MessageEnvelope
    envelope = MessageEnvelope(
        message_id=final_execution_id,
        message_content=_extract_message_content(query),
        message_chain=getattr(query, 'message_chain', []),
        sender_id=str(getattr(query, 'sender_id', '')),
        sender_name=getattr(query, 'sender_name', ''),
        platform=getattr(query, 'platform', ''),
        session_id=f"{getattr(query, 'launcher_type', 'person')}_{getattr(query, 'launcher_id', '')}",
        conversation_id=query.variables.get('conversation_id', ''),
        launcher_type=getattr(query, 'launcher_type', 'person'),
        launcher_id=getattr(query, 'launcher_id', ''),
        is_group=getattr(query, 'launcher_type', 'person') == 'group',
        bot_id=getattr(query, 'bot_uuid', ''),
        user_id=getattr(query, 'sender_id', ''),
        mentions=query.variables.get('mentions', []),
        reply_to=query.variables.get('reply_to'),
        raw_message=query.variables.get('raw_message', {}),
        variables=query.variables,
        conversation_variables=query.variables.get('conversation_variables', {}),
        response=response_text,
        response_chain=response_chain,
        status=status,
        execution_id=final_execution_id,
        workflow_id=final_workflow_id,
        trigger_type='message',
    )
    
    return envelope


def execution_context_to_query_variables(
    context: ExecutionContext,
) -> Dict[str, Any]:
    """将 ExecutionContext 转换为 Query 变量字典
    
    Args:
        context: 执行上下文
    
    Returns:
        变量字典
    """
    variables = {
        '_workflow_execution_id': context.execution_id,
        '_workflow_id': context.workflow_id,
        '_workflow_version': context.workflow_version,
        '_workflow_status': context.status.value,
        **(context.variables or {}),
    }
    
    # 添加会话变量
    if context.conversation_variables:
        variables['conversation_variables'] = context.conversation_variables
    
    # 添加消息上下文
    if context.message_context:
        variables['message'] = context.message_context.message_content
        variables['sender_id'] = context.message_context.sender_id
        variables['sender_name'] = context.message_context.sender_name
        variables['platform'] = context.message_context.platform
        variables['conversation_id'] = context.message_context.conversation_id
    
    return variables


def query_variables_to_execution_context(
    variables: Dict[str, Any],
    execution_id: str,
    workflow_id: str,
) -> ExecutionContext:
    """从 Query 变量字典创建 ExecutionContext
    
    Args:
        variables: Query 变量字典
        execution_id: 执行 ID
        workflow_id: 工作流 ID
    
    Returns:
        ExecutionContext 对象
    """
    # 提取工作流版本
    workflow_version = variables.get('_workflow_version', 1)
    
    # 提取状态
    status_str = variables.get('_workflow_status', 'running')
    try:
        status = ExecutionStatus(status_str)
    except ValueError:
        status = ExecutionStatus.RUNNING
    
    # 提取会话变量
    conversation_variables = variables.get('conversation_variables', {})
    
    # 构建消息上下文
    message_context = None
    if variables.get('message'):
        message_context = MessageContext(
            message_id=variables.get('message_id', ''),
            message_content=variables.get('message', ''),
            sender_id=variables.get('sender_id', ''),
            sender_name=variables.get('sender_name', ''),
            platform=variables.get('platform', ''),
            conversation_id=variables.get('conversation_id', ''),
            is_group=variables.get('is_group', False),
            group_id=variables.get('group_id'),
            mentions=variables.get('mentions', []),
            reply_to=variables.get('reply_to'),
            raw_message=variables.get('raw_message', {}),
        )
    
    # 创建 ExecutionContext
    context = ExecutionContext(
        execution_id=execution_id,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        status=status,
        variables=variables,
        conversation_variables=conversation_variables,
        message_context=message_context,
    )
    
    return context


# ============================================================================
# 内部辅助函数
# ============================================================================

def _build_message_event(envelope: MessageEnvelope) -> Any:
    """构建消息事件对象
    
    根据 launcher_type 构建相应的消息事件（FriendMessage 或 GroupMessage）
    """
    # 这里需要根据实际的 Pipeline 实现来构建
    # 暂时返回一个简单的字典，实际使用时需要导入真实的消息事件类
    return {
        'sender_id': envelope.sender_id,
        'sender_name': envelope.sender_name,
        'platform': envelope.platform,
        'timestamp': datetime.now().isoformat(),
    }


def _build_message_chain(envelope: MessageEnvelope) -> Any:
    """构建消息链
    
    如果 envelope 已有 message_chain，直接使用；
    否则从 message_content 构建
    """
    if envelope.message_chain:
        return envelope.message_chain
    
    # 从 message_content 构建简单的消息链
    # 这里需要根据实际的 Pipeline 实现来构建
    return [{'type': 'text', 'content': envelope.message_content}]


def _extract_response_text(query: Any) -> Optional[str]:
    """从 Query 中提取响应文本"""
    resp_messages = getattr(query, 'resp_messages', [])
    if not resp_messages:
        return None
    
    last_msg = resp_messages[-1]
    if hasattr(last_msg, 'content'):
        return last_msg.content
    elif isinstance(last_msg, dict) and 'content' in last_msg:
        return last_msg['content']
    
    return str(last_msg)


def _extract_response_chain(query: Any) -> List[Any]:
    """从 Query 中提取响应消息链"""
    return getattr(query, 'resp_message_chain', [])


def _extract_message_content(query: Any) -> str:
    """从 Query 中提取消息内容"""
    message_chain = getattr(query, 'message_chain', [])
    if not message_chain:
        return ''
    
    # 简单地将消息链转换为字符串
    if isinstance(message_chain, str):
        return message_chain
    
    return str(message_chain)


# ============================================================================
# 变量命名空间验证
# ============================================================================

RESERVED_PREFIXES = {
    '_': '内部变量，系统使用',
    'loop_': '循环变量',
    'nodes.': '节点输出引用',
    'variables.': '执行变量引用',
    'conversation_variables.': '会话变量引用',
    'message.': '消息上下文引用',
}


def validate_variable_name(name: str) -> Tuple[bool, Optional[str]]:
    """验证变量名是否符合命名空间规范
    
    Args:
        name: 变量名
    
    Returns:
        (是否有效, 错误信息)
    
    Example:
        >>> valid, error = validate_variable_name('_internal')
        >>> valid
        True
        >>> valid, error = validate_variable_name('user_name')
        >>> valid
        True
    """
    if not name:
        return False, '变量名不能为空'
    
    if not isinstance(name, str):
        return False, '变量名必须是字符串'
    
    # 检查是否以保留前缀开头
    for prefix, description in RESERVED_PREFIXES.items():
        if name.startswith(prefix):
            # 某些前缀是允许的（如 _ 用于内部变量）
            if prefix == '_':
                # 内部变量只能由系统设置
                return True, None
            elif prefix in ('loop_', 'nodes.', 'variables.', 'conversation_variables.', 'message.'):
                # 这些是系统自动生成的，用户不应该手动设置
                return False, f'变量名不能以 "{prefix}" 开头（{description}）'
    
    # 检查变量名格式
    if not name[0].isalpha() and name[0] != '_':
        return False, '变量名必须以字母或下划线开头'
    
    if not all(c.isalnum() or c == '_' for c in name):
        return False, '变量名只能包含字母、数字和下划线'
    
    return True, None


def validate_variables_dict(variables: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """验证变量字典中的所有变量名
    
    Args:
        variables: 变量字典
    
    Returns:
        (是否全部有效, 错误信息列表)
    
    Example:
        >>> valid, errors = validate_variables_dict({'user_name': 'Alice', '_internal': 123})
        >>> valid
        True
        >>> errors
        []
    """
    errors = []
    
    for name in variables.keys():
        is_valid, error = validate_variable_name(name)
        if not is_valid and error:
            errors.append(f'{name}: {error}')
    
    return len(errors) == 0, errors
