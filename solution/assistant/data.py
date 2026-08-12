"""Load the 7 CSVs into an in-memory, indexed store.

The dataset is a closed world (~130 rows). Deterministic joins on
account_id / person_id / event_id / source_id beat semantic search at this
scale and keep citations exact.

CSV column expectations are aligned with the provided data_dictionary.md.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

FILES = [
    "accounts", "people", "events", "event_attendance",
    "activities", "relationships", "sources",
]

EXPECTED_COLUMNS = {
    "accounts": [
        "account_id", "account_name", "country", "region", "sector",
        "subsector", "ownership_type", "membership_status", "account_manager",
        "family_owned", "business_description", "tags", "sensitivity_level",
    ],
    "people": [
        "person_id", "full_name", "account_id", "role_title",
        "relationship_to_company", "is_family_member", "generation", "email",
        "phone", "contact_visibility", "bio_note", "sensitivity_level",
    ],
    "events": [
        "event_id", "event_name", "city", "region", "event_date",
        "event_type", "status", "description",
    ],
    "event_attendance": [
        "attendance_id", "event_id", "person_id", "account_id",
        "attendance_status", "attendee_category", "rsvp_date", "source_id",
        "notes",
    ],
    "activities": [
        "activity_id", "activity_date", "account_id", "person_id",
        "activity_type", "title", "summary", "region", "themes", "visibility",
        "sensitivity_level", "source_id",
    ],
    "relationships": [
        "relationship_id", "from_person_id", "from_account_id", "to_person_id",
        "to_account_id", "relationship_type", "strength", "basis",
        "visibility", "source_id", "notes",
    ],
    "sources": [
        "source_id", "source_type", "title", "publisher_or_origin",
        "publication_date", "url", "excerpt", "reliability", "visibility",
    ],
}


def _default_data_dir() -> Path:
    env = os.environ.get("FORUM_DATA_DIR")
    if env:
        return Path(env)
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = repo_root / "data"
    if data_dir.is_dir():
        return data_dir
    # Backward-compatible fallback for older layouts with CSVs at repo root.
    return repo_root


class Store:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else _default_data_dir()
        self.tables: dict[str, list[dict]] = {}
        for name in FILES:
            path = self.data_dir / f"{name}.csv"
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                expected = EXPECTED_COLUMNS[name]
                actual = reader.fieldnames or []
                if actual != expected:
                    raise ValueError(
                        f"{path.name} columns do not match data_dictionary.md.\n"
                        f"Expected: {expected}\n"
                        f"Actual:   {actual}"
                    )
                self.tables[name] = list(reader)

        # primary-key indexes
        self.people = {r["person_id"]: r for r in self.tables["people"]}
        self.accounts = {r["account_id"]: r for r in self.tables["accounts"]}
        self.events = {r["event_id"]: r for r in self.tables["events"]}
        self.sources = {r["source_id"]: r for r in self.tables["sources"]}
        self.activities = {r["activity_id"]: r for r in self.tables["activities"]}

    # -- joins -----------------------------------------------------------
    def people_of_account(self, account_id: str) -> list[dict]:
        return [p for p in self.tables["people"] if p["account_id"] == account_id]

    def attendance_for_event(self, event_id: str) -> list[dict]:
        return [a for a in self.tables["event_attendance"] if a["event_id"] == event_id]

    def attendance_for_person(self, person_id: str) -> list[dict]:
        return [a for a in self.tables["event_attendance"] if a["person_id"] == person_id]

    def attendance_for_account(self, account_id: str) -> list[dict]:
        return [a for a in self.tables["event_attendance"] if a["account_id"] == account_id]

    def activities_for_account(self, account_id: str) -> list[dict]:
        return [a for a in self.tables["activities"] if a["account_id"] == account_id]

    def activities_for_person(self, person_id: str) -> list[dict]:
        return [a for a in self.tables["activities"] if a["person_id"] == person_id]

    def relationships_touching_person(self, person_id: str) -> list[dict]:
        return [
            r for r in self.tables["relationships"]
            if person_id in (r["from_person_id"], r["to_person_id"])
        ]

    def relationships_touching_account(self, account_id: str) -> list[dict]:
        return [
            r for r in self.tables["relationships"]
            if account_id in (r["from_account_id"], r["to_account_id"])
        ]

    def source(self, source_id: str) -> dict | None:
        return self.sources.get(source_id)
