import pytest # type: ignore
from datetime import datetime
from pathlib import Path
from pydantic import ValidationError
from langbot_plugin.api.entities.builtin.platform.message import (
    MessageChain,
    MessageComponent,
    Plain,
    At,
    AtAll,
    Image,
    Source,
    Quote,
    Forward,
    ForwardMessageNode,
    ForwardMessageDiaplay,
)

def test_message_chain_creation():
    """测试消息链的创建"""
    # 测试从组件列表创建
    chain = MessageChain([Plain(text="Hello"), At(target=123456)])
    assert len(chain) == 2
    assert isinstance(chain[0], Plain)
    assert isinstance(chain[1], At)
    assert chain[0].text == "Hello"
    assert chain[1].target == 123456

    # 测试无效输入
    with pytest.raises(ValueError):
        MessageChain("Hello")  # 不能直接传入字符串
    
    with pytest.raises(ValueError):
        MessageChain([123])  # 不能传入非 MessageComponent 类型

def test_message_chain_operations():
    """测试消息链的操作"""
    chain = MessageChain([Plain(text="Hello"), At(target=123456)])
    
    # 测试字符串表示
    assert str(chain) == "Hello@123456"
    
    # 测试索引访问
    assert isinstance(chain[0], Plain)
    assert isinstance(chain[1], At)
    
    # 测试切片
    sliced = chain[0:1]
    assert len(sliced) == 1
    assert isinstance(sliced[0], Plain)
    
    # 测试修改元素
    chain[0] = Plain(text="Hi")
    assert chain[0].text == "Hi"
    
    # 测试删除元素
    del chain[0]
    assert len(chain) == 1
    assert isinstance(chain[0], At)

def test_message_chain_list_operations():
    """测试消息链的列表操作"""
    chain = MessageChain([Plain(text="Hello")])
    
    # 测试 append
    chain.append(At(target=123456))
    assert len(chain) == 2
    assert isinstance(chain[1], At)
    
    # 测试 insert
    chain.insert(0, AtAll())
    assert len(chain) == 3
    assert isinstance(chain[0], AtAll)
    
    # 测试 extend
    chain.extend([Plain(text="World"), At(target=789012)])
    assert len(chain) == 5
    assert isinstance(chain[3], Plain)
    assert isinstance(chain[4], At)
    
    # 测试 pop
    component = chain.pop()
    assert isinstance(component, At)
    assert component.target == 789012
    
    # 测试 remove
    chain.remove(At(target=123456))
    assert len(chain) == 3
    
    # 测试 clear
    chain.clear()
    assert len(chain) == 0

def test_message_chain_concatenation():
    """测试消息链的连接操作"""
    chain1 = MessageChain([Plain(text="Hello")])
    chain2 = MessageChain([Plain(text="World")])
    
    # 测试加法操作
    result = chain1 + chain2
    assert len(result) == 2
    assert str(result) == "HelloWorld"
    
    # 测试原地加法操作
    chain1 += chain2
    assert len(chain1) == 2
    assert str(chain1) == "HelloWorld"

def test_message_chain_serialization():
    """测试消息链的序列化和反序列化"""
    # 创建一个包含多种组件的消息链
    current_time = datetime.now()
    original_chain = MessageChain([
        Source(id=12345, time=current_time),
        Plain(text="Hello"),
        At(target=123456),
        AtAll(),
        Image(image_id="test_image_id", url="http://example.com/image.jpg"),
        Quote(
            id=12345,
            group_id=67890,
            sender_id=11111,
            target_id=22222,
            origin=MessageChain([Plain(text="Original message")])
        )
    ])
    
    # 序列化消息链
    serialized = original_chain.model_dump()
    
    # 反序列化消息链
    deserialized_chain = MessageChain.model_validate(serialized)
    
    # 验证反序列化后的消息链
    assert len(deserialized_chain) == len(original_chain)
    
    # 验证每个组件的类型和属性
    assert isinstance(deserialized_chain[0], Source)
    assert deserialized_chain[0].id == 12345
    assert isinstance(deserialized_chain[0].time, datetime)
    
    assert isinstance(deserialized_chain[1], Plain)
    assert deserialized_chain[1].text == "Hello"
    
    assert isinstance(deserialized_chain[2], At)
    assert deserialized_chain[2].target == 123456
    
    assert isinstance(deserialized_chain[3], AtAll)
    
    assert isinstance(deserialized_chain[4], Image)
    assert deserialized_chain[4].image_id == "test_image_id"
    assert str(deserialized_chain[4].url) == "http://example.com/image.jpg"
    
    assert isinstance(deserialized_chain[5], Quote)
    assert deserialized_chain[5].id == 12345
    assert deserialized_chain[5].group_id == 67890
    assert deserialized_chain[5].sender_id == 11111
    assert deserialized_chain[5].target_id == 22222
    assert isinstance(deserialized_chain[5].origin, MessageChain)
    assert deserialized_chain[5].origin[0].text == "Original message"

def test_message_chain_contains():
    """测试消息链的包含操作"""
    chain = MessageChain([Plain(text="Hello"), At(target=123456), AtAll()])
    
    # 测试类型检查
    assert Plain in chain
    assert At in chain
    assert AtAll in chain
    
    # 测试组件检查
    assert Plain(text="Hello") in chain
    assert At(target=123456) in chain
    assert At(target=789012) not in chain


def test_message_chain_with_source():
    """测试带源信息的消息链"""
    source = Source(id=12345, time=datetime.now())
    chain = MessageChain([source, Plain(text="Hello")])
    
    assert chain.source is not None
    assert chain.source.id == 12345
    assert chain.message_id == 12345

def test_message_chain_with_quote():
    """测试带引用的消息链"""
    quote = Quote(
        id=12345,
        group_id=67890,
        sender_id=11111,
        target_id=22222,
        origin=MessageChain([Plain(text="Original message")])
    )
    chain = MessageChain([quote, Plain(text="Reply")])
    
    assert len(chain) == 2
    assert isinstance(chain[0], Quote)
    assert chain[0].id == 12345

def test_message_chain_with_forward():
    """测试带转发的消息链"""
    display = ForwardMessageDiaplay(
        title="Test Forward",
        brief="[Forward]",
        source="Test",
        preview=["Message 1", "Message 2"],
        summary="View 2 forwarded messages"
    )
    node = ForwardMessageNode(
        sender_id=12345,
        sender_name="Test User",
        message_chain=MessageChain([Plain(text="Test message")]),
        time=datetime.now()
    )
    forward = Forward(display=display, node_list=[node])
    chain = MessageChain([forward])
    
    assert len(chain) == 1
    assert isinstance(chain[0], Forward)
    assert chain[0].display.title == "Test Forward"

def test_message_chain_with_image():
    """测试带图片的消息链"""
    image = Image(
        image_id="test_image_id",
        url="http://example.com/image.jpg"
    )
    chain = MessageChain([image, Plain(text="Image description")])
    
    assert len(chain) == 2
    assert isinstance(chain[0], Image)
    assert chain[0].image_id == "test_image_id"

def test_message_chain_validation():
    """测试消息链的验证"""
    # 测试空消息链
    chain = MessageChain([])
    assert len(chain) == 0
    
    # 测试无效组件类型
    with pytest.raises(ValueError):
        MessageChain([123])  # 整数不是有效的消息组件
