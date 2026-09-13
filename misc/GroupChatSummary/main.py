from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any

from langbot_plugin.api.definition.plugin import BasePlugin
from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.api.entities.builtin.provider import message as provider_message


class GroupChatSummary(BasePlugin):
    """Group chat message collector and summarizer.

    Collects messages from group chats and provides LLM-powered summaries
    via commands, tool calls, or automatic triggers.
    """

    def __init__(self):
        super().__init__()
        # {group_key: [{"sender": str, "text": str, "time": float}, ...]}
        self.message_buffer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # {group_key: last_auto_summary_index}
        self.auto_summary_watermark: dict[str, int] = {}
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:
        """Load persisted message buffers from storage."""
        try:
            data = await self.get_plugin_storage("message_buffers")
            if data:
                loaded = json.loads(data.decode("utf-8"))
                for k, v in loaded.items():
                    self.message_buffer[k] = v
                self.logger.info(
                    f"Loaded message buffers for {len(loaded)} groups"
                )
        except Exception:
            self.logger.info("No persisted message buffers found, starting fresh")

        try:
            data = await self.get_plugin_storage("auto_summary_watermark")
            if data:
                self.auto_summary_watermark = json.loads(data.decode("utf-8"))
        except Exception:
            pass

    def _group_key(self, launcher_type: str, launcher_id: str | int) -> str:
        """Generate a unique key for a group."""
        return f"{launcher_type}_{launcher_id}"

    def _get_max_messages(self) -> int:
        config = self.get_config()
        return config.get("max_messages", 500)

    def _get_default_summary_count(self) -> int:
        config = self.get_config()
        return config.get("default_summary_count", 100)

    async def record_message(
        self,
        launcher_type: str,
        launcher_id: str | int,
        sender_id: str | int,
        sender_name: str,
        text: str,
        bot_uuid: str | None = None,
    ) -> None:
        """Record a group message into the buffer.

        Args:
            launcher_type: "group" or "person"
            launcher_id: Group ID
            sender_id: Sender's user ID
            sender_name: Display name of sender
            text: Message text content
            bot_uuid: Bot UUID for auto-summary
        """
        if not text or not text.strip():
            return

        key = self._group_key(launcher_type, launcher_id)
        max_messages = self._get_max_messages()

        self.message_buffer[key].append({
            "sender_id": str(sender_id),
            "sender": sender_name or str(sender_id),
            "text": text.strip(),
            "time": time.time(),
        })

        # Trim buffer if too large
        if len(self.message_buffer[key]) > max_messages:
            self.message_buffer[key] = self.message_buffer[key][-max_messages:]

        # Persist periodically (every 10 messages)
        if len(self.message_buffer[key]) % 10 == 0:
            await self._persist_buffers()

        # Check auto-summary trigger
        config = self.get_config()
        if config.get("auto_summary_enabled", False) and bot_uuid:
            threshold = config.get("auto_summary_threshold", 200)
            watermark = self.auto_summary_watermark.get(key, 0)
            current_count = len(self.message_buffer[key])

            if current_count - watermark >= threshold:
                self.auto_summary_watermark[key] = current_count
                await self._persist_watermark()
                # Fire auto-summary in background
                asyncio.create_task(
                    self._auto_summarize(key, bot_uuid, launcher_type, str(launcher_id))
                )

    async def _persist_buffers(self) -> None:
        """Persist message buffers to plugin storage."""
        try:
            data = json.dumps(dict(self.message_buffer), ensure_ascii=False)
            await self.set_plugin_storage("message_buffers", data.encode("utf-8"))
        except Exception as e:
            self.logger.error(f"Failed to persist message buffers: {e}")

    async def _persist_watermark(self) -> None:
        """Persist auto-summary watermark to plugin storage."""
        try:
            data = json.dumps(self.auto_summary_watermark, ensure_ascii=False)
            await self.set_plugin_storage(
                "auto_summary_watermark", data.encode("utf-8")
            )
        except Exception as e:
            self.logger.error(f"Failed to persist watermark: {e}")

    def get_recent_messages(
        self,
        launcher_type: str,
        launcher_id: str | int,
        count: int | None = None,
        hours: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent messages from a group.

        Args:
            launcher_type: "group" or "person"
            launcher_id: Group ID
            count: Number of recent messages (default from config)
            hours: Filter messages from last N hours

        Returns:
            List of message dicts
        """
        key = self._group_key(launcher_type, launcher_id)
        messages = self.message_buffer.get(key, [])

        if hours is not None:
            cutoff = time.time() - hours * 3600
            messages = [m for m in messages if m["time"] >= cutoff]

        if count is not None:
            messages = messages[-count:]
        else:
            default_count = self._get_default_summary_count()
            messages = messages[-default_count:]

        return messages

    def get_message_count(self, launcher_type: str, launcher_id: str | int) -> int:
        """Get the number of stored messages for a group."""
        key = self._group_key(launcher_type, launcher_id)
        return len(self.message_buffer.get(key, []))

    def _get_summary_language(self) -> str:
        config = self.get_config()
        lang = config.get("language", "zh_Hans")
        lang_map = {
            "zh_Hans": "Chinese (Simplified)",
            "en_US": "English",
            "ja_JP": "Japanese",
        }
        return lang_map.get(lang, "Chinese (Simplified)")

    def build_summary_prompt(
        self, messages: list[dict[str, Any]], language: str | None = None
    ) -> str:
        """Build the LLM prompt for summarizing messages.

        Args:
            messages: List of message dicts
            language: Override language for summary

        Returns:
            Formatted prompt string
        """
        if not language:
            language = self._get_summary_language()

        # Format messages into readable text
        lines = []
        for msg in messages:
            ts = time.strftime("%H:%M", time.localtime(msg["time"]))
            lines.append(f"[{ts}] {msg['sender']}: {msg['text']}")

        chat_log = "\n".join(lines)

        prompt = f"""Please summarize the following group chat conversation. 
Focus on:
1. Key topics discussed
2. Important decisions or conclusions
3. Action items or tasks mentioned
4. Notable opinions or disagreements

Output the summary in {language}.
Keep it concise but comprehensive. Use bullet points for clarity.
If there are multiple topics, group them with headers.

---
Chat Log ({len(messages)} messages):
{chat_log}
---"""
        return prompt

    async def generate_summary(
        self,
        launcher_type: str,
        launcher_id: str | int,
        count: int | None = None,
        hours: float | None = None,
    ) -> str:
        """Generate a summary using LLM.

        Args:
            launcher_type: "group" or "person"
            launcher_id: Group ID
            count: Number of messages to summarize
            hours: Summarize messages from last N hours

        Returns:
            Summary text
        """
        messages = self.get_recent_messages(launcher_type, launcher_id, count, hours)

        if not messages:
            return self._get_no_messages_text()

        if len(messages) < 3:
            return self._get_too_few_messages_text(len(messages))

        prompt = self.build_summary_prompt(messages)

        # Use LLM to generate summary
        try:
            # Use configured model or fall back to first available
            configured_model = self.get_config().get("model")
            if configured_model:
                llm_model_uuid = configured_model
            else:
                llm_models = await self.get_llm_models()
                if not llm_models:
                    return "Error: No LLM model available."
                llm_model_uuid = llm_models[0]

            response = await self.invoke_llm(
                llm_model_uuid=llm_model_uuid,
                messages=[
                    provider_message.Message(
                        role="user",
                        content=[provider_message.ContentElement.from_text(prompt)],
                    )
                ],
            )

            # Extract text from response
            if response.content:
                if isinstance(response.content, str):
                    return response.content
                elif isinstance(response.content, list):
                    parts = []
                    for elem in response.content:
                        if hasattr(elem, "text") and elem.text:
                            parts.append(elem.text)
                    return "\n".join(parts) if parts else "Failed to generate summary."

            return "Failed to generate summary."

        except Exception as e:
            self.logger.error(f"LLM invocation failed: {e}", exc_info=True)
            return f"Error generating summary: {str(e)}"

    async def _auto_summarize(
        self,
        group_key: str,
        bot_uuid: str,
        target_type: str,
        target_id: str,
    ) -> None:
        """Auto-summarize and send to group."""
        try:
            parts = group_key.split("_", 1)
            if len(parts) != 2:
                return

            launcher_type, launcher_id = parts

            summary = await self.generate_summary(
                launcher_type=launcher_type,
                launcher_id=launcher_id,
            )

            config = self.get_config()
            lang = config.get("language", "zh_Hans")
            prefix = "📋 Auto Summary" if lang == "en_US" else "📋 自动总结"

            message_chain = platform_message.MessageChain([
                platform_message.Plain(text=f"{prefix}\n\n{summary}")
            ])

            await self.send_message(
                bot_uuid=bot_uuid,
                target_type=target_type,
                target_id=target_id,
                message_chain=message_chain,
            )
        except Exception as e:
            self.logger.error(f"Auto-summary failed: {e}", exc_info=True)

    def _get_no_messages_text(self) -> str:
        config = self.get_config()
        lang = config.get("language", "zh_Hans")
        if lang == "en_US":
            return "No messages recorded in this group yet."
        elif lang == "ja_JP":
            return "このグループにはまだメッセージが記録されていません。"
        return "当前群聊还没有记录到消息。"

    def _get_too_few_messages_text(self, count: int) -> str:
        config = self.get_config()
        lang = config.get("language", "zh_Hans")
        if lang == "en_US":
            return f"Only {count} messages recorded, too few to summarize meaningfully."
        elif lang == "ja_JP":
            return f"メッセージが {count} 件しか記録されていません。要約するには少なすぎます。"
        return f"仅记录了 {count} 条消息，内容太少无法生成有意义的总结。"

    def __del__(self):
        self.logger.info("GroupChatSummary plugin unloaded")
