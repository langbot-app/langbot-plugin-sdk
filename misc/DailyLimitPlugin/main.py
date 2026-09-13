from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone, timedelta

from langbot_plugin.api.definition.plugin import BasePlugin

STATE_KEY = "daily_limit_state"

DEFAULT_LIMIT_MESSAGE = "您今天的对话次数已达上限，请明天再来吧~"


class DailyLimitPlugin(BasePlugin):
    """Daily conversation limit per session.

    Tracks per-session daily usage, supports per-session limit overrides,
    a global default limit for new sessions, manual reset, silent mode and
    timezone-aware daily rollover. All state is persisted via plugin storage
    and shared with the management Page component via ``self.plugin``.

    State shape (persisted JSON under ``daily_limit_state``):

        {
          "settings": {
            "default_limit": 50,
            "limit_message": "...",
            "silent_mode": false,
            "tz_offset": 8,
            "reset_hour": 0
          },
          "sessions": {
            "<session_id>": {
              "label": "person:12345",
              "limit": null,          # null = use default_limit; int = override
              "count": 3,
              "date": "2026-06-20",   # logical day the count belongs to
              "last_active": "2026-06-20T11:20:00+08:00"
            }
          }
        }
    """

    settings: dict
    sessions: dict
    _lock: asyncio.Lock

    def __init__(self):
        super().__init__()
        self.settings = {}
        self.sessions = {}
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------------- lifecycle

    async def initialize(self) -> None:
        self._lock = asyncio.Lock()
        loaded = None
        try:
            raw = await self.get_plugin_storage(STATE_KEY)
            if raw:
                loaded = json.loads(raw.decode("utf-8"))
        except Exception as e:
            print(f"[DailyLimit] No saved state ({e}); seeding from config", flush=True)

        cfg = self.get_config() or {}
        seed = {
            "default_limit": int(cfg.get("daily_limit", 50)),
            "limit_message": cfg.get("limit_message") or DEFAULT_LIMIT_MESSAGE,
            "silent_mode": bool(cfg.get("silent_mode", False)),
            "tz_offset": int(cfg.get("reset_timezone_offset", 8)),
            "reset_hour": int(cfg.get("reset_hour", 0)),
        }

        if loaded and isinstance(loaded, dict):
            self.settings = {**seed, **(loaded.get("settings") or {})}
            self.sessions = loaded.get("sessions") or {}
        else:
            self.settings = seed
            self.sessions = {}
        self._normalize_settings()
        print(
            f"[DailyLimit] initialized: default_limit={self.settings['default_limit']}, "
            f"{len(self.sessions)} tracked sessions",
            flush=True,
        )

    async def destroy(self) -> None:
        pass

    # ------------------------------------------------------------------- helpers

    def _normalize_settings(self) -> None:
        s = self.settings
        s["default_limit"] = max(0, int(s.get("default_limit", 50)))
        s["tz_offset"] = max(-12, min(14, int(s.get("tz_offset", 8))))
        s["reset_hour"] = max(0, min(23, int(s.get("reset_hour", 0))))
        s["silent_mode"] = bool(s.get("silent_mode", False))
        if not s.get("limit_message"):
            s["limit_message"] = DEFAULT_LIMIT_MESSAGE

    def _logical_today(self) -> str:
        tz = timezone(timedelta(hours=self.settings["tz_offset"]))
        now_local = datetime.now(tz)
        if now_local.hour < self.settings["reset_hour"]:
            now_local -= timedelta(days=1)
        return now_local.strftime("%Y-%m-%d")

    def _now_iso(self) -> str:
        tz = timezone(timedelta(hours=self.settings["tz_offset"]))
        return datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S%z")

    def _effective_limit(self, sess: dict) -> int:
        override = sess.get("limit")
        if override is None:
            return self.settings["default_limit"]
        return int(override)

    async def persist(self) -> None:
        await self.set_plugin_storage(
            STATE_KEY,
            json.dumps(
                {"settings": self.settings, "sessions": self.sessions},
                ensure_ascii=False,
            ).encode("utf-8"),
        )

    # --------------------------------------------------------- runtime (listener)

    async def check_and_count(self, session_id: str, label: str) -> tuple[bool, str]:
        """Check the session against its limit and increment if allowed.

        Returns ``(allowed, message)``. When ``allowed`` is False and the
        message is non-empty, the listener should reply with it; an empty
        message means "block silently".
        """
        async with self._lock:
            today = self._logical_today()
            sess = self.sessions.get(session_id)
            if sess is None:
                sess = {"label": label, "limit": None, "count": 0, "date": today}
                self.sessions[session_id] = sess

            # Roll over the day if needed
            if sess.get("date") != today:
                sess["date"] = today
                sess["count"] = 0
            sess["label"] = label
            sess["last_active"] = self._now_iso()

            limit = self._effective_limit(sess)

            # 0 means unlimited
            if limit <= 0:
                sess["count"] = int(sess.get("count", 0)) + 1
                await self.persist()
                return True, ""

            if int(sess.get("count", 0)) >= limit:
                await self.persist()
                if self.settings.get("silent_mode"):
                    return False, ""
                return False, self.settings.get("limit_message") or DEFAULT_LIMIT_MESSAGE

            sess["count"] = int(sess.get("count", 0)) + 1
            await self.persist()
            return True, ""

    # ----------------------------------------------------------- management (page)

    def snapshot(self) -> dict:
        """Return a JSON-serializable view of current state for the Page."""
        today = self._logical_today()
        rows = []
        for sid, sess in self.sessions.items():
            count = int(sess.get("count", 0)) if sess.get("date") == today else 0
            rows.append(
                {
                    "id": sid,
                    "label": sess.get("label", sid),
                    "limit": sess.get("limit"),
                    "effective_limit": self._effective_limit(sess),
                    "count": count,
                    "date": sess.get("date"),
                    "last_active": sess.get("last_active"),
                }
            )
        rows.sort(key=lambda r: (r.get("last_active") or ""), reverse=True)
        return {
            "settings": dict(self.settings),
            "today": today,
            "sessions": rows,
        }

    async def update_settings(self, patch: dict) -> None:
        allowed = {"default_limit", "limit_message", "silent_mode", "tz_offset", "reset_hour"}
        for k, v in (patch or {}).items():
            if k in allowed and v is not None:
                self.settings[k] = v
        self._normalize_settings()
        await self.persist()

    async def set_session_limit(self, session_id: str, limit) -> bool:
        sess = self.sessions.get(session_id)
        if sess is None:
            return False
        if limit is None or limit == "":
            sess["limit"] = None
        else:
            sess["limit"] = max(0, int(limit))
        await self.persist()
        return True

    async def reset_session(self, session_id: str) -> bool:
        sess = self.sessions.get(session_id)
        if sess is None:
            return False
        sess["count"] = 0
        sess["date"] = self._logical_today()
        await self.persist()
        return True

    async def reset_all(self) -> int:
        today = self._logical_today()
        n = 0
        for sess in self.sessions.values():
            sess["count"] = 0
            sess["date"] = today
            n += 1
        await self.persist()
        return n

    async def delete_session(self, session_id: str) -> bool:
        if session_id in self.sessions:
            del self.sessions[session_id]
            await self.persist()
            return True
        return False
