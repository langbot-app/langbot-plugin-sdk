# Provider 消息中的 Base64 文件

`ContentElement.from_file_base64()` 表示由 Runner 或插件生成的内联文件。`Message` 和 `MessageChunk` 的 `get_content_platform_message_chain()` 会将该元素转换为 `File(base64=..., name=...)`，供平台适配器消费。

## 使用示例

```python
import base64

from langbot_plugin.api.entities.builtin.platform.message import File
from langbot_plugin.api.entities.builtin.provider.message import ContentElement, Message

data = "报告内容\n".encode("utf-8")
message = Message(
    role="assistant",
    content=[
        ContentElement.from_text("文件已生成。"),
        ContentElement.from_file_base64(
            base64.b64encode(data).decode("ascii"), "报告.txt"
        ),
    ],
)
chain = message.get_content_platform_message_chain()
assert isinstance(chain[1], File)
assert chain[1].name == "报告.txt"
assert base64.b64decode(chain[1].base64) == data
```

流式输出使用 `MessageChunk` 构造相同的 `content`。这些文件元素经 `RunnerResult.message_delta()`、`message_completed()` 或携带最终消息的 `run_completed()` 序列化往返后仍然保留。

## 转换规则

- Base64 字符串和文件名原样传递，不下载、解码或重写载荷。
- 缺少 `file_base64`（值为 `None`）时跳过该元素；空字符串则保留为零字节文件组件。
- 缺省文件名或 `file_name=None` 转换为平台 `File` 的默认空名。
- 文件与文字、图片、URL 文件按原内容顺序转换。`prefix_text` 只加在第一个文字组件上；没有文字时，在文件前插入文字前缀。
- Host 已解析的 `attachments` 继续追加在转换内容之后，不进入模型或插件协议；重复转换不修改原始消息及附件。
- SDK 转换成功只说明文件组件已保留。实际发送能力、附件大小和格式限制仍由目标平台及适配器决定。

## 本地回归

在 SDK 仓库根目录执行：

```bash
uv sync --dev --python 3.12
uv run --no-sync pytest tests/api/entities/builtin/test_provider_message.py \
  tests/api/entities/builtin/test_provider_message_files.py \
  tests/api/entities/builtin/runner/test_context_result.py tests/test_message.py -q
```

本修复不新增字段、配置、环境变量或依赖。LangBot 使用固定版本的 SDK；运行中的实例需在包含修复的 SDK 发布并被其采用后，才能取得该行为。
