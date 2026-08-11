"""Deterministic natural-language composition.

The engine decides *what* is sayable; this module decides *how* to say it.
No model required — the prose is assembled from the same gated evidence the
structured view uses, so the two can never disagree.

Pronouns: the dataset records no pronouns for anyone, so people are referred
to by name or with they/them. Inferring gender from a name would be a
fabricated attribute like any other.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- phrasing
VISIBILITY_PHRASE = {
    "public": "publicly reported",
    "internal": "recorded internally",
    "restricted": "restricted",
}

SOURCE_PHRASE = {
    "public_press": "public press",
    "company_site_update": "a company announcement",
    "internal_crm_note": "an internal CRM note",
    "meeting_note": "a meeting note",
    "event_rsvp": "the event system",
    "research_note": "a research note",
}


def evidence_phrase(label: dict) -> str:
    """'publicly reported via public press (high reliability)'"""
    vis = VISIBILITY_PHRASE.get(label.get("visibility", ""), label.get("visibility", ""))
    src = SOURCE_PHRASE.get(label.get("source_type", ""), "")
    rel = label.get("reliability", "")
    bits = [vis]
    if src:
        bits.append(f"via {src}")
    text = " ".join(bits)
    if rel and rel != "high":
        text += f", {rel} reliability"
    return text


def cite(rec_id: str, label: dict | None = None) -> str:
    """Compact inline citation: [ACT009 · S011 · public]"""
    parts = [rec_id]
    if label:
        if label.get("source_id"):
            parts.append(label["source_id"])
        if label.get("visibility"):
            parts.append(label["visibility"])
    return "[" + " · ".join(parts) + "]"


def oxford(items: list[str], conj: str = "and") -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conj} {items[1]}"
    return ", ".join(items[:-1]) + f" {conj} {items[-1]}"


def count_noun(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def person_ref(person: dict) -> str:
    """Name plus role, for first mention."""
    role = person.get("role_title")
    return f"{person['full_name']}{f' ({role})' if role else ''}"


def natural_text(text: str) -> str:
    """Remove dash characters and smooth phrasing for visible responses."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r"(?<=\w)-(?=\w)", " ", text)
    text = re.sub(r"\s-\s", ", ", text)
    text = re.sub(r"(?m)^\s*•\s*", "", text)
    lines = []
    for line in text.splitlines():
        if not line.strip():
            lines.append("")
            continue
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"\s+,", ",", line)
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class Narrative:
    """Accumulates prose paragraphs, keeping citations attached to claims."""

    def __init__(self):
        self.paragraphs: list[str] = []

    def para(self, text: str) -> "Narrative":
        text = natural_text(" ".join(text.split()))
        if text:
            self.paragraphs.append(text)
        return self

    def bullets(self, lead: str, items: list[str]) -> "Narrative":
        if not items:
            return self
        intro = natural_text(" ".join(lead.split()))
        body = "; ".join(
            natural_text(" ".join(item.split()))
            for item in items
            if item and item.strip()
        )
        if not body:
            return self
        text = f"{intro} {body}".strip() if intro else body
        if text[-1] not in ".!?":
            text += "."
        self.paragraphs.append(text)
        return self

    def render(self) -> str:
        return natural_text("\n\n".join(self.paragraphs))

    def __bool__(self) -> bool:
        return bool(self.paragraphs)
