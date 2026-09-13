import re
import logging
import aiohttp
from html.parser import HTMLParser

from langbot_plugin.api.definition.plugin import BasePlugin
from langbot_plugin.api.entities.builtin.provider.message import Message, ContentElement


class _TextExtractor(HTMLParser):
    """Simple HTML to text extractor."""

    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False
        self._skip_tags = {'script', 'style', 'noscript', 'header', 'footer', 'nav'}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False
        if tag in ('p', 'br', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li'):
            self._text.append('\n')

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def get_text(self) -> str:
        return re.sub(r'\n{3,}', '\n\n', ''.join(self._text)).strip()


URL_PATTERN = re.compile(r'https?://[^\s<>\]\)]+')

LANG_MAP = {
    'zh_Hans': '请用简体中文回复',
    'en_US': 'Please reply in English',
    'ja_JP': '日本語で回答してください',
}


class URLSummary(BasePlugin):

    async def initialize(self):
        self.logger = logging.getLogger("URLSummary")
        self.logger.info("URLSummary plugin initialized")

    async def fetch_page(self, url: str, max_len: int) -> tuple[str, str]:
        """Fetch a web page and return (title, text_content)."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; LangBot-URLSummary/1.0)',
            'Accept': 'text/html,application/xhtml+xml',
        }
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True, ssl=False) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                content_type = resp.headers.get('Content-Type', '')
                if 'text/html' not in content_type and 'application/xhtml' not in content_type:
                    raise Exception(f"Not HTML: {content_type}")
                html = await resp.text(errors='replace')

        # Extract title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else url

        # Extract text
        extractor = _TextExtractor()
        extractor.feed(html)
        text = extractor.get_text()[:max_len]

        return title, text

    async def summarize(self, url: str, title: str, content: str, model_uuid: str, language: str) -> str:
        """Use LLM to summarize the page content."""
        lang_instruction = LANG_MAP.get(language, LANG_MAP['zh_Hans'])

        prompt = f"""{lang_instruction}。

请总结以下网页内容，生成简洁的摘要。包含关键信息和要点。

网页标题: {title}
网页链接: {url}

网页内容:
{content}"""

        msg = Message(
            role="user",
            content=[ContentElement.from_text(prompt)],
        )

        response = await self.invoke_llm(
            messages=[msg],
            llm_model_uuid=model_uuid,
        )

        if isinstance(response.content, str):
            return response.content
        elif isinstance(response.content, list):
            parts = []
            for elem in response.content:
                if hasattr(elem, 'text'):
                    parts.append(elem.text)
            return ''.join(parts)
        return str(response.content)
