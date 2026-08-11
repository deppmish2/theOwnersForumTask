"""Session notes: temporary, conversation-provided updates.

Kept strictly separate from the dataset (never written to the CSVs).
Notes are cited as SN-ids and always labeled `session note — unverified,
not part of the dataset`.
"""

from __future__ import annotations

from datetime import datetime, timezone


class SessionStore:
    def __init__(self):
        self._notes: list[dict] = []

    def add(self, text: str, entities: list[str] | None = None) -> dict:
        note = {
            "note_id": f"SN{len(self._notes) + 1:03d}",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "text": text.strip(),
            "entities": entities or [],
        }
        self._notes.append(note)
        return note

    def all(self) -> list[dict]:
        return list(self._notes)

    def for_entity(self, entity_id: str) -> list[dict]:
        return [n for n in self._notes if entity_id in n["entities"]]
