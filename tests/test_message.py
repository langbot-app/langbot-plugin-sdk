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
    # 直接用 Plain 创建
    chain = MessageChain([Plain("Hello World")])
    assert len(chain) == 1
    assert isinstance(chain[0], Plain)
    assert chain[0].text == "Hello World"

    # parse_obj 支持字符串
    chain2 = MessageChain.parse_obj(["Hello World"])
    assert len(chain2) == 1
    assert isinstance(chain2[0], Plain)
    assert chain2[0].text == "Hello World"

    # 测试从组件列表创建
    chain = MessageChain([Plain("Hello"), At(123456)])
    assert len(chain) == 2
    assert isinstance(chain[0], Plain)
    assert isinstance(chain[1], At)
    assert chain[0].text == "Hello"
    assert chain[1].target == 123456

    # 测试从混合类型创建
    chain = MessageChain.parse_obj(["Hello", At(123456)])
    assert len(chain) == 2
    assert isinstance(chain[0], Plain)
    assert isinstance(chain[1], At)

def test_message_chain_operations():
    """测试消息链的操作"""
    chain = MessageChain([Plain("Hello"), At(123456)])
    
    # 测试字符串表示
    assert str(chain) == "Hello@123456"
    
    # 测试获取第一个组件
    plain = chain.get_first(Plain)
    assert plain is not None
    assert plain.text == "Hello"
    
    # 测试索引访问
    assert isinstance(chain[0], Plain)
    assert isinstance(chain[1], At)
    
    # 测试切片
    sliced = chain[0:1]
    assert len(sliced) == 1
    assert isinstance(sliced[0], Plain)

def test_message_chain_contains():
    """测试消息链的包含操作"""
    chain = MessageChain([Plain("Hello"), At(123456), AtAll()])
    
    # 测试类型检查
    assert Plain in chain
    assert At in chain
    assert AtAll in chain
    
    # 测试组件检查
    assert Plain("Hello") in chain
    assert At(123456) in chain
    assert At(789012) not in chain

def test_message_chain_concatenation():
    """测试消息链的连接操作"""
    chain1 = MessageChain([Plain("Hello")])
    chain2 = MessageChain([Plain("World")])
    
    # 测试加法操作
    result = chain1 + chain2
    assert len(result) == 2
    assert str(result) == "HelloWorld"
    
    # 测试与字符串连接
    result = chain1 + "World"
    assert len(result) == 2
    assert str(result) == "HelloWorld"
    
    # 测试与组件连接
    result = chain1 + At(123456)
    assert len(result) == 2
    assert str(result) == "Hello@123456"

def test_message_chain_methods():
    """测试消息链的方法"""
    chain = MessageChain([Plain("Hello"), At(123456), Plain("World")])
    
    # 测试 count 方法
    assert chain.count(Plain) == 2
    assert chain.count(At) == 1
    
    # 测试 index 方法
    assert chain.index(Plain) == 0
    assert chain.index(At) == 1
    
    # 测试 exclude 方法
    filtered = chain.exclude(Plain)
    assert len(filtered) == 1
    assert isinstance(filtered[0], At)

def test_message_chain_with_source():
    """测试带源信息的消息链"""
    source = Source(id=12345, time=datetime.now())
    chain = MessageChain([source, Plain("Hello")])
    
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
        origin=MessageChain([Plain("Original message")])
    )
    chain = MessageChain([quote, Plain("Reply")])
    
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
        message_chain=MessageChain([Plain("Test message")]),
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
    chain = MessageChain([image, Plain("Image description")])
    
    assert len(chain) == 2
    assert isinstance(chain[0], Image)
    assert chain[0].image_id == "test_image_id"

def test_message_chain_validation():
    """测试消息链的验证"""
    # 测试空消息链
    chain = MessageChain([])
    assert len(chain) == 0
    
    # 测试无效组件类型
    with pytest.raises(ValidationError):
        MessageChain([123])  # 整数不是有效的消息组件
    
    # 测试无效的组件参数
    with pytest.raises(ValueError):
        Image(path="nonexistent.jpg")  # 不存在的图片路径 