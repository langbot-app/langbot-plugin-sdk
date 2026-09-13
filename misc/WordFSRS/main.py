# WordFSRS - Spaced-repetition vocabulary plugin for LangBot.
# Memory scheduling powered by py-fsrs (the FSRS algorithm, the same memory
# model behind Maimemo / 墨墨背单词).
from __future__ import annotations

import os
import sys
import json
import time
import datetime
from typing import Any, Optional

from langbot_plugin.api.definition.plugin import BasePlugin

from fsrs import Scheduler, Card, Rating

# Allow importing the plugin-level i18n module.
sys.path.insert(0, os.path.dirname(__file__))
from i18n import get_text  # noqa: E402


# Rating aliases users can type after `!word grade <word>`.
RATING_ALIASES: dict[str, Rating] = {
    "1": Rating.Again,
    "again": Rating.Again,
    "wrong": Rating.Again,
    "no": Rating.Again,
    "忘了": Rating.Again,
    "不会": Rating.Again,
    "2": Rating.Hard,
    "hard": Rating.Hard,
    "难": Rating.Hard,
    "模糊": Rating.Hard,
    "3": Rating.Good,
    "good": Rating.Good,
    "ok": Rating.Good,
    "会": Rating.Good,
    "记得": Rating.Good,
    "4": Rating.Easy,
    "easy": Rating.Easy,
    "简单": Rating.Easy,
    "秒了": Rating.Easy,
}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class WordFSRSPlugin(BasePlugin):
    """Entry point and shared state for the WordFSRS plugin.

    All persistent vocabulary data is scoped per *session*
    (``{launcher_type}:{launcher_id}``) so private chats and groups each keep
    their own deck. State is stored as JSON via the plugin KV storage.
    """

    async def initialize(self) -> None:
        cfg = self.get_config() or {}
        self.language: str = cfg.get("language", "en_US") or "en_US"
        self.daily_new_limit: int = int(cfg.get("daily_new_limit", 20) or 0)
        retention = float(cfg.get("desired_retention", 0.9) or 0.9)
        retention = min(0.97, max(0.7, retention))
        self.scheduler = Scheduler(desired_retention=retention)

    def get_language(self) -> str:
        return getattr(self, "language", "en_US")

    def t(self, key: str, **kwargs) -> str:
        return get_text(self.get_language(), key, **kwargs)

    # ---------------------------------------------------------------- storage

    @staticmethod
    def _storage_key(session_id: str) -> str:
        return f"deck:{session_id}"

    async def _load_deck(self, session_id: str) -> dict[str, Any]:
        """Load a session deck. Returns a fresh deck on first use."""
        try:
            raw = await self.get_plugin_storage(self._storage_key(session_id))
        except Exception:
            raw = None
        if not raw:
            return {"cards": {}, "new_intro": {}}
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except Exception:
            return {"cards": {}, "new_intro": {}}
        data.setdefault("cards", {})
        data.setdefault("new_intro", {})  # {date_str: count} of new cards introduced
        return data

    async def _save_deck(self, session_id: str, deck: dict[str, Any]) -> None:
        payload = json.dumps(deck, ensure_ascii=False).encode("utf-8")
        await self.set_plugin_storage(self._storage_key(session_id), payload)

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _due_dt(card_entry: dict[str, Any]) -> datetime.datetime:
        card = Card.from_dict(card_entry["fsrs"])
        due = card.due
        if due.tzinfo is None:
            due = due.replace(tzinfo=datetime.timezone.utc)
        return due

    def _is_due(self, card_entry: dict[str, Any], at: datetime.datetime) -> bool:
        return self._due_dt(card_entry) <= at

    def _fmt_when(self, due: datetime.datetime) -> str:
        """Human-friendly 'due in ...' string (localized)."""
        delta = due - _now()
        secs = delta.total_seconds()
        if secs <= 0:
            return self.t("when.now")
        mins = secs / 60
        if mins < 60:
            return self.t("when.minutes", n=int(round(mins)))
        hours = mins / 60
        if hours < 24:
            return self.t("when.hours", h=f"{hours:.1f}")
        days = hours / 24
        return self.t("when.days", d=f"{days:.1f}")

    # ----------------------------------------------------------------- actions

    async def add_word(
        self, session_id: str, word: str, meaning: str = ""
    ) -> tuple[bool, str]:
        """Add a new vocabulary card. Returns (created, message)."""
        word = word.strip()
        if not word:
            return False, self.t("add.usage")
        deck = await self._load_deck(session_id)
        key = word.lower()
        if key in deck["cards"]:
            entry = deck["cards"][key]
            if meaning:
                entry["meaning"] = meaning
                await self._save_deck(session_id, deck)
                return False, self.t("add.updated", word=word, meaning=meaning)
            return False, self.t("add.exists", word=word)
        card = Card()
        deck["cards"][key] = {
            "word": word,
            "meaning": meaning,
            "fsrs": card.to_dict(),
            "added_at": time.time(),
            "reviews": 0,
        }
        await self._save_deck(session_id, deck)
        total = len(deck["cards"])
        tip = self.t("add.meaning_line", meaning=meaning) if meaning else ""
        return True, self.t("add.ok", word=word, tip=tip, total=total)

    async def remove_word(self, session_id: str, word: str) -> str:
        deck = await self._load_deck(session_id)
        key = word.strip().lower()
        if key not in deck["cards"]:
            return self.t("del.not_found", word=word)
        del deck["cards"][key]
        await self._save_deck(session_id, deck)
        return self.t("del.ok", word=word, total=len(deck["cards"]))

    async def next_due(self, session_id: str) -> tuple[Optional[str], str]:
        """Pick the next card to review.

        Priority: cards already due (earliest due first). If none are due but the
        daily new-card budget allows, introduce a brand-new card. Returns
        (card_key, message).
        """
        deck = await self._load_deck(session_id)
        cards = deck["cards"]
        if not cards:
            return None, self.t("review.empty")

        now = _now()
        due_items = []
        new_items = []
        for k, e in cards.items():
            is_new = e.get("reviews", 0) == 0
            if is_new:
                new_items.append((k, e))
            elif self._is_due(e, now):
                due_items.append((k, self._due_dt(e), e))

        if due_items:
            due_items.sort(key=lambda x: x[1])
            k, _, e = due_items[0]
            return k, self._format_question(e, deck, session_id, kind="review")

        if new_items:
            today = now.date().isoformat()
            introduced_today = deck["new_intro"].get(today, 0)
            if self.daily_new_limit == 0 or introduced_today < self.daily_new_limit:
                k, e = new_items[0]
                return k, self._format_question(e, deck, session_id, kind="new")
            else:
                soonest = self._soonest_msg(cards, now)
                return None, self.t(
                    "review.new_limit", limit=self.daily_new_limit, soonest=soonest
                )

        soonest = self._soonest_msg(cards, now)
        return None, self.t("review.none_due", soonest=soonest)

    def _soonest_msg(self, cards: dict, now: datetime.datetime) -> str:
        future = [
            self._due_dt(e)
            for e in cards.values()
            if e.get("reviews", 0) > 0
        ]
        if not future:
            return self.t("soonest.all_done")
        nxt = min(future)
        return self.t("soonest.next", when=self._fmt_when(nxt))

    def _format_question(
        self, entry: dict, deck: dict, session_id: str, kind: str
    ) -> str:
        word = entry["word"]
        kind_label = self.t("q.kind_new") if kind == "new" else self.t("q.kind_review")
        body = self.t("q.body", kind=kind_label, word=word)
        if kind == "new":
            meaning = entry.get("meaning", "")
            if meaning:
                body += self.t("q.new_meaning", meaning=meaning)
        return body

    async def show_answer(self, session_id: str, word: str) -> str:
        deck = await self._load_deck(session_id)
        key = word.strip().lower()
        e = deck["cards"].get(key)
        if not e:
            return self.t("del.not_found", word=word)
        meaning = e.get("meaning") or self.t("show.no_meaning")
        return self.t("show.ok", word=e["word"], meaning=meaning)

    async def grade(
        self, session_id: str, word: str, rating_token: str
    ) -> str:
        deck = await self._load_deck(session_id)
        key = word.strip().lower()
        e = deck["cards"].get(key)
        if not e:
            return self.t("grade.not_found", word=word)
        rating = RATING_ALIASES.get(rating_token.strip().lower())
        if rating is None:
            return self.t("grade.invalid")
        was_new = e.get("reviews", 0) == 0
        card = Card.from_dict(e["fsrs"])
        card, _log = self.scheduler.review_card(card, rating)
        e["fsrs"] = card.to_dict()
        e["reviews"] = e.get("reviews", 0) + 1
        e["last_rating"] = int(rating)

        if was_new:
            today = _now().date().isoformat()
            deck["new_intro"][today] = deck["new_intro"].get(today, 0) + 1

        await self._save_deck(session_id, deck)
        due = card.due
        if due.tzinfo is None:
            due = due.replace(tzinfo=datetime.timezone.utc)
        rating_key = {
            1: "grade.rating_again",
            2: "grade.rating_hard",
            3: "grade.rating_good",
            4: "grade.rating_easy",
        }[int(rating)]
        rating_label = self.t(rating_key)
        meaning = e.get("meaning")
        meaning_line = self.t("grade.meaning_paren", meaning=meaning) if meaning else ""
        return self.t(
            "grade.ok",
            word=e["word"],
            meaning=meaning_line,
            rating=rating_label,
            when=self._fmt_when(due),
        )

    async def stats(self, session_id: str) -> str:
        deck = await self._load_deck(session_id)
        cards = deck["cards"]
        if not cards:
            return self.t("stats.empty")
        now = _now()
        total = len(cards)
        new_cnt = sum(1 for e in cards.values() if e.get("reviews", 0) == 0)
        due_cnt = sum(
            1
            for e in cards.values()
            if e.get("reviews", 0) > 0 and self._is_due(e, now)
        )
        learning = total - new_cnt
        today = now.date().isoformat()
        intro_today = deck["new_intro"].get(today, 0)
        limit_str = self.t("stats.unlimited") if self.daily_new_limit == 0 else str(self.daily_new_limit)
        return self.t(
            "stats.body",
            total=total,
            due=due_cnt,
            new=new_cnt,
            learning=learning,
            intro=intro_today,
            limit=limit_str,
        )

    async def list_words(self, session_id: str, page: int = 1) -> str:
        deck = await self._load_deck(session_id)
        cards = list(deck["cards"].values())
        if not cards:
            return self.t("list.empty")
        cards.sort(key=lambda e: self._due_dt(e))
        per = 15
        page = max(1, page)
        start = (page - 1) * per
        chunk = cards[start : start + per]
        if not chunk:
            return self.t("list.no_more")
        lines = [self.t("list.header")]
        for e in chunk:
            meaning = e.get("meaning", "")
            mtxt = f" \u2014 {meaning}" if meaning else ""
            if e.get("reviews", 0) == 0:
                status = self.t("list.status_new")
            else:
                status = self._fmt_when(self._due_dt(e))
            lines.append(self.t("list.item", word=e["word"], meaning=mtxt, status=status))
        total_pages = (len(cards) + per - 1) // per
        lines.append(
            self.t("list.footer", page=page, total_pages=total_pages, count=len(cards))
        )
        return "\n".join(lines)

    def __del__(self) -> None:
        pass
