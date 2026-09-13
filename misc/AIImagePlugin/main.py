from __future__ import annotations

from langbot_plugin.api.definition.plugin import BasePlugin

class AIImagePlugin(BasePlugin):

    def __init__(self):
        super().__init__()
        self.openai_client = None

    async def initialize(self) -> None:
        """插件初始化，验证配置并创建 OpenAI 客户端"""
        
        # 获取用户配置
        config = self.get_config()
        api_key = config.get('openai_api_key', '')
        base_url = config.get('api_base_url', 'https://api.qhaigc.net')
        
        if not api_key:
            self.log("警告: 未配置 API Key，插件功能将无法使用")
            return
        
        # 导入并初始化 OpenAI 客户端
        try:
            from openai import AsyncOpenAI
            self.openai_client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url
            )
            self.log(f"OpenAI 兼容客户端初始化成功，API 地址: {base_url}")
        except Exception as e:
            self.log(f"初始化客户端失败: {e}")
    
    def log(self, message: str):
        """辅助日志方法"""
        print(f"[AIImagePlugin] {message}")