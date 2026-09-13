from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langbot_plugin.api.definition.plugin import BasePlugin

logger = logging.getLogger("MCBotPlugin")

# Plugin storage keys
BINDINGS_KEY = "mcbot_bindings"  # {group_key: "addr:port"}
RECORDS_KEY = "mcbot_records"    # [{"server","players","duration","ts"}, ...]

# Keep at most 14 days of online records to bound storage growth
RECORD_RETENTION_SECONDS = 14 * 24 * 60 * 60


class MCBotPlugin(BasePlugin):
    """Minecraft server helper plugin.

    Binds a Minecraft server to a chat group, reports live server status and
    online players, and tracks per-player online time via a background poller.

    Migrated from the legacy QChatGPT/LangBot plugin: MongoDB storage is
    replaced by the built-in plugin key-value storage, and the synchronous
    `mctools` ping plus thread-based routine are replaced by async `mcstatus`
    and an asyncio background task.
    """

    def __init__(self):
        super().__init__()
        # In-memory caches, loaded from / persisted to plugin storage.
        self.bindings: dict[str, str] = {}
        self.records: list[dict[str, Any]] = []
        self._track_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def initialize(self) -> None:
        await self._load_state()
        # Launch the background playtime tracker.
        self._track_task = asyncio.create_task(self._track_loop())
        logger.info("[MCBot] initialized, %d binding(s) loaded", len(self.bindings))

    def __del__(self):
        task = getattr(self, "_track_task", None)
        if task and not task.done():
            task.cancel()

    # ------------------------------------------------------------------ #
    # Storage helpers
    # ------------------------------------------------------------------ #
    async def _load_state(self) -> None:
        self.bindings = await self._load_json(BINDINGS_KEY, default={})
        self.records = await self._load_json(RECORDS_KEY, default=[])

    async def _load_json(self, key: str, default: Any) -> Any:
        try:
            raw = await self.get_plugin_storage(key)
            if not raw:
                return default
            return json.loads(raw.decode("utf-8"))
        except Exception:
            # Missing key / version mismatch — start fresh.
            return default

    async def _save_bindings(self) -> None:
        try:
            data = json.dumps(self.bindings, ensure_ascii=False).encode("utf-8")
            await self.set_plugin_storage(BINDINGS_KEY, data)
        except Exception as e:
            logger.error("[MCBot] failed to persist bindings: %s", e)

    async def _save_records(self) -> None:
        try:
            data = json.dumps(self.records, ensure_ascii=False).encode("utf-8")
            await self.set_plugin_storage(RECORDS_KEY, data)
        except Exception as e:
            logger.error("[MCBot] failed to persist records: %s", e)

    # ------------------------------------------------------------------ #
    # Binding management (used by commands)
    # ------------------------------------------------------------------ #
    @staticmethod
    def group_key(launcher_type: str, launcher_id: str | int) -> str:
        return f"{launcher_type}_{launcher_id}"

    async def bind_server(self, group_key: str, server_addr: str) -> None:
        self.bindings[group_key] = server_addr
        await self._save_bindings()

    async def unbind_server(self, group_key: str) -> bool:
        if group_key in self.bindings:
            del self.bindings[group_key]
            await self._save_bindings()
            return True
        return False

    def get_bound_server(self, group_key: str) -> str | None:
        return self.bindings.get(group_key)

    # ------------------------------------------------------------------ #
    # Minecraft server ping (async, via mcstatus)
    # ------------------------------------------------------------------ #
    def _ping_timeout(self) -> float:
        try:
            return float(self.get_config().get("ping_timeout", 10))
        except Exception:
            return 10.0

    async def ping_server(self, server_addr: str) -> dict[str, Any]:
        """Ping a Minecraft Java server and return normalized status info.

        Returns a dict: {"motd": str, "version": str, "online": int,
        "max": int, "players": [name, ...]}. Raises on failure.
        """
        from mcstatus import JavaServer

        timeout = self._ping_timeout()
        server = await JavaServer.async_lookup(server_addr, timeout=timeout)
        status = await server.async_status()

        sample = []
        if status.players.sample:
            sample = [p.name for p in status.players.sample]

        # MOTD: prefer plain text rendering across mcstatus versions.
        motd = ""
        try:
            motd = status.motd.to_plain()
        except Exception:
            try:
                motd = status.description if isinstance(status.description, str) else ""
            except Exception:
                motd = ""

        return {
            "motd": motd,
            "version": status.version.name,
            "online": status.players.online,
            "max": status.players.max,
            "players": sample,
        }

    # ------------------------------------------------------------------ #
    # Playtime tracking
    # ------------------------------------------------------------------ #
    def _track_interval(self) -> int:
        try:
            return max(15, int(self.get_config().get("track_interval", 60)))
        except Exception:
            return 60

    async def _track_loop(self) -> None:
        """Background task: periodically ping all bound servers and record
        which players were online, to build playtime statistics."""
        # Small startup delay so initialize() fully settles.
        await asyncio.sleep(10)
        while True:
            interval = self._track_interval()
            try:
                await self._track_once(interval)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("[MCBot] track loop error: %s", e)
            await asyncio.sleep(interval)

    async def _track_once(self, duration: int) -> None:
        servers = sorted(set(self.bindings.values()))
        if not servers:
            return

        changed = False
        now = time.time()
        for server_addr in servers:
            try:
                info = await self.ping_server(server_addr)
            except Exception:
                # Server offline / unreachable — skip this cycle.
                continue
            players = info["players"]
            if players:
                self.records.append({
                    "server": server_addr,
                    "players": players,
                    "duration": duration,
                    "ts": now,
                })
                changed = True

        # Trim old records.
        cutoff = now - RECORD_RETENTION_SECONDS
        before = len(self.records)
        self.records = [r for r in self.records if r.get("ts", 0) >= cutoff]
        if len(self.records) != before:
            changed = True

        if changed:
            await self._save_records()

    def count_playtime(
        self, server_addr: str, period_minutes: int
    ) -> list[tuple[str, int]]:
        """Aggregate per-player online seconds for a server over the last
        `period_minutes`. Returns a list of (player, seconds) sorted desc."""
        cutoff = time.time() - period_minutes * 60
        totals: dict[str, int] = {}
        for rec in self.records:
            if rec.get("server") != server_addr:
                continue
            if rec.get("ts", 0) < cutoff:
                continue
            duration = rec.get("duration", 0)
            for player in rec.get("players", []):
                totals[player] = totals.get(player, 0) + duration
        return sorted(totals.items(), key=lambda x: x[1], reverse=True)
