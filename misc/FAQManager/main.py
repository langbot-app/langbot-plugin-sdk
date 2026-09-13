from __future__ import annotations

import json
import uuid

from langbot_plugin.api.definition.plugin import BasePlugin

STORAGE_KEY = 'faq_entries'


class FAQManagerPlugin(BasePlugin):
    """FAQ Manager — maintain a set of question-answer pairs.

    Data is persisted via plugin storage so it survives restarts.
    The Page component provides a CRUD UI; the Tool component lets the
    LLM search entries during conversations.

    State lives here so that both Page and Tool components can access
    it via ``self.plugin``.
    """

    entries: list[dict[str, str]]

    def __init__(self):
        super().__init__()
        self.entries = []

    async def initialize(self) -> None:
        try:
            raw = await self.get_plugin_storage(STORAGE_KEY)
            self.entries = json.loads(raw.decode('utf-8'))
            print(f'[FAQManager] Loaded {len(self.entries)} entries from storage', flush=True)
        except Exception as e:
            print(f'[FAQManager] Failed to load storage: {e}', flush=True)
            self.entries = []

    async def persist(self) -> None:
        await self.set_plugin_storage(
            STORAGE_KEY,
            json.dumps(self.entries, ensure_ascii=False).encode('utf-8'),
        )

    def search(self, query: str) -> list[dict[str, str]]:
        """Simple keyword search across questions and answers."""
        q = query.lower()
        return [
            e for e in self.entries
            if q in e['question'].lower() or q in e['answer'].lower()
        ]

    def add_entry(self, question: str, answer: str) -> dict[str, str]:
        entry = {
            'id': uuid.uuid4().hex[:8],
            'question': question,
            'answer': answer,
        }
        self.entries.append(entry)
        return entry

    def update_entry(self, entry_id: str, question: str | None, answer: str | None) -> dict[str, str] | None:
        for entry in self.entries:
            if entry['id'] == entry_id:
                if question is not None:
                    entry['question'] = question.strip()
                if answer is not None:
                    entry['answer'] = answer.strip()
                return entry
        return None

    def delete_entry(self, entry_id: str) -> bool:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e['id'] != entry_id]
        return len(self.entries) < before
