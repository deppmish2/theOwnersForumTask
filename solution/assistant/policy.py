"""Policy gate: contact visibility, evidence labeling, sensitivity, staleness.

Rules reconstructed from the case-study briefing (policies.md was not
included in the provided folder — flagged in NOTES.md).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# ---------------------------------------------------------------- contacts
CONTACT_RULES = {
    "shareable_business": {"email": True, "phone": True,
                           "note": "business email and phone may be shown"},
    "email_only":         {"email": True, "phone": False,
                           "note": "email may be shown; phone must not be shared"},
    "restricted":         {"email": False, "phone": False,
                           "note": "contact details restricted — permission from the "
                                   "relationship owner is required before sharing"},
    "internal_only":      {"email": False, "phone": False,
                           "note": "contact details are internal-only and must not be "
                                   "shared externally"},
}


def contact_view(person: dict) -> dict:
    """Return the sharable slice of a person's contact details + rationale."""
    rule = CONTACT_RULES.get(person.get("contact_visibility", "restricted"),
                             CONTACT_RULES["restricted"])
    out = {"policy": person.get("contact_visibility"), "note": rule["note"],
           "email": None, "phone": None}
    if rule["email"]:
        out["email"] = person.get("email")
    if rule["phone"]:
        out["phone"] = person.get("phone")
    return out


# ------------------------------------------------------------- sensitivity
SENSITIVE_THEMES = {
    "succession", "ownership transition", "governance", "external chair",
    "family governance", "sensitive", "sale", "health", "family",
}

SENSITIVE_QUERY_PATTERNS = [
    r"\bsuccession\b", r"\bownership (change|transition|transfer)\b",
    r"\bsell(ing)?\b", r"\bfor sale\b", r"\ba sale\b", r"\bexit\b",
    r"\bgovernance\b", r"\bheir\b", r"\binherit", r"\bhealth\b",
    r"\bfamily (matter|dispute|council|dynamic)", r"\bstepping down\b",
    r"\bexternal chair\b",
]

# 'family-owned' is a company descriptor, not a sensitive family matter
_SENSITIVE_EXCLUSIONS = [r"\bfamily[- ]owned\b", r"\bfamily (business|enterprise)\b"]


def query_is_sensitive(text: str) -> bool:
    t = text.lower()
    for excl in _SENSITIVE_EXCLUSIONS:
        t = re.sub(excl, " ", t)
    return any(re.search(p, t) for p in SENSITIVE_QUERY_PATTERNS)


def record_is_sensitive(rec: dict) -> bool:
    themes = set((rec.get("themes") or "").split(";"))
    if themes & SENSITIVE_THEMES:
        return True
    return rec.get("sensitivity_level") in ("confidential", "restricted")


def record_is_restricted(rec: dict) -> bool:
    return (rec.get("visibility") == "restricted"
            or rec.get("sensitivity_level") == "restricted")


# ---------------------------------------------------------------- evidence
def evidence_label(store, rec: dict) -> dict:
    """Visibility + reliability label for an activity/attendance/relationship row."""
    src = store.source(rec.get("source_id", "")) or {}
    return {
        "source_id": rec.get("source_id"),
        "visibility": rec.get("visibility") or src.get("visibility") or "internal",
        "reliability": src.get("reliability", "unknown"),
        "source_type": src.get("source_type", "unknown"),
        "publication_date": src.get("publication_date", ""),
    }


STALE_AFTER_DAYS = 365


def dataset_today(store) -> date:
    """Anchor 'now' to the newest date in the dataset, not the wall clock."""
    dates = []
    for t in ("activities", "event_attendance"):
        for r in store.tables[t]:
            d = r.get("activity_date") or r.get("rsvp_date") or ""
            try:
                dates.append(date.fromisoformat(d))
            except ValueError:
                pass
    return max(dates) if dates else date.today()


def is_stale(store, rec: dict) -> bool:
    if "stale" in (rec.get("themes") or ""):
        return True
    d = rec.get("activity_date", "")
    try:
        return date.fromisoformat(d) < dataset_today(store) - timedelta(days=STALE_AFTER_DAYS)
    except ValueError:
        return False


# -------------------------------------------------------------- gate result
def gate_record(store, rec: dict) -> dict:
    """Classify one evidence record for the composer.

    disposition:
      show            — usable, label visibility/reliability
      show_with_caveat— usable but weak (stale / low reliability / unverified)
      withhold        — restricted; existence may be acknowledged, content withheld,
                        human-review flag raised
    """
    label = evidence_label(store, rec)
    if record_is_restricted(rec) or label["visibility"] == "restricted":
        return {"disposition": "withhold", "label": label,
                "reason": "restricted note — content withheld, requires human review"}
    caveats = []
    if label["reliability"] == "low" or "unverified" in (rec.get("themes") or ""):
        caveats.append("low-reliability / unverified source")
    if is_stale(store, rec):
        caveats.append("stale — may be out of date")
    if rec.get("sensitivity_level") == "confidential":
        caveats.append("confidential — internal handling only")
    if caveats:
        return {"disposition": "show_with_caveat", "label": label,
                "reason": "; ".join(caveats)}
    return {"disposition": "show", "label": label, "reason": ""}
