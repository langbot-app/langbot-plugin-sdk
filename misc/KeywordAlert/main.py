from __future__ import annotations

import logging
import time
from typing import Optional

from langbot_plugin.api.definition.plugin import BasePlugin

logger = logging.getLogger("KeywordAlert")


class KeywordAlert(BasePlugin):
    """Monitor group messages for keywords and alert admins via private message."""

    def __init__(self):
        super().__init__()
        # Cooldown tracking: {(group_id, keyword): last_alert_timestamp}
        self._cooldowns: dict[tuple[str, str], float] = {}

    async def initialize(self):
        logger.info("KeywordAlert plugin initialized")

    def parse_keywords(self) -> list[str]:
        raw = self.get_config().get("keywords", "")
        return [k.strip() for k in raw.split(",") if k.strip()]

    def parse_group_ids(self) -> Optional[set[str]]:
        raw = self.get_config().get("group_ids", "")
        if not raw or not raw.strip():
            return None  # Monitor all groups
        return {g.strip() for g in raw.split(",") if g.strip()}

    def check_cooldown(self, group_id: str, keyword: str) -> bool:
        """Returns True if alert is allowed (not in cooldown)."""
        config = self.get_config()
        cooldown = int(config.get("cooldown_seconds", 60))
        key = (group_id, keyword)
        now = time.time()
        last = self._cooldowns.get(key, 0)
        if now - last < cooldown:
            return False
        self._cooldowns[key] = now
        return True

    async def send_alert(self, group_id: str, sender_id: str, keyword: str, text: str):
        """Send private alert to admin."""
        from langbot_plugin.api.entities.builtin.platform import message as platform_message

        config = self.get_config()
        admin_id = config.get("admin_id", "")
        if not admin_id:
            logger.warning("No admin_id configured, skipping alert")
            return

        bot_uuid = config.get("bot")
        if not bot_uuid:
            bots = await self.get_bots()
            if not bots:
                logger.warning("No bots available to send alert")
                return
            bot_uuid = bots[0]

        alert_text = (
            f"🔔 关键词告警\n"
            f"━━━━━━━━━━━━━━\n"
            f"关键词: {keyword}\n"
            f"群组: {group_id}\n"
            f"发送者: {sender_id}\n"
            f"━━━━━━━━━━━━━━\n"
            f"{text[:500]}"
        )

        chain = platform_message.MessageChain([
            platform_message.Plain(text=alert_text)
        ])

        try:
            await self.send_message(
                bot_uuid=bot_uuid,
                target_type="person",
                target_id=admin_id,
                message_chain=chain,
            )
            logger.info(f"Alert sent: keyword='{keyword}' group={group_id}")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
