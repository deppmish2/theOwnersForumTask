"""Entity resolution and intent detection.

Names/IDs resolve deterministically against the closed dataset. If a
mention could be several people/accounts/events, we return all candidates
and the engine asks a clarifying question instead of guessing (policy:
Ambiguity).
"""

from __future__ import annotations

import re

from .data import Store

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class Mention:
    def __init__(self, kind: str, record: dict, matched: str):
        self.kind = kind          # person | account | event
        self.record = record
        self.matched = matched

    @property
    def id(self) -> str:
        return (self.record.get("person_id") or self.record.get("account_id")
                or self.record.get("event_id"))

    @property
    def name(self) -> str:
        return (self.record.get("full_name") or self.record.get("account_name")
                or self.record.get("event_name"))


def resolve_entities(store: Store, text: str) -> dict:
    """Return {'people': [...], 'accounts': [...], 'events': [...],
    'ambiguous': {surface: [Mention,...]}}"""
    low = " " + text.lower() + " "
    out = {"people": [], "accounts": [], "events": [], "ambiguous": {}}

    # explicit record ids (P001 / A004 / E005) — how a user answers a clarify
    for rid in re.findall(r"\b([PAE]\d{3})\b", text.upper()):
        if rid in store.people:
            out["people"].append(Mention("person", store.people[rid], rid))
        elif rid in store.accounts:
            out["accounts"].append(Mention("account", store.accounts[rid], rid))
        elif rid in store.events:
            out["events"].append(Mention("event", store.events[rid], rid))
    if out["people"] or out["accounts"] or out["events"]:
        return out

    # people by full name — unambiguous, so resolve these first
    for p in store.tables["people"]:
        if p["full_name"].lower() in low:
            out["people"].append(Mention("person", p, p["full_name"]))
    named_people = {m.id for m in out["people"]}

    # accounts: exact account name, else a distinctive first word ("Northstar")
    consumed_by_account: set[str] = set()
    for a in store.tables["accounts"]:
        name = a["account_name"].lower()
        first = name.split()[0]
        exact = name in low
        if exact or re.search(rf"\b{re.escape(first)}\b", low):
            # "Elise Valen" alone is a person, not the Valen Group account —
            # but "Valen Group" (exact) is the account even though people share
            # the surname.
            if not exact and any(first in m.name.lower() for m in out["people"]):
                continue
            out["accounts"].append(Mention("account", a, a["account_name"]))
            consumed_by_account.update(name.split())

    # Partial-name fallback: match either the given name or the surname, for
    # tokens the account match didn't already claim. A token shared by several
    # people (two Maras) becomes an ambiguity rather than a guess.
    if not out["people"]:
        by_token: dict[str, dict[str, dict]] = {}
        for p in store.tables["people"]:
            parts = p["full_name"].split()
            for tok in {parts[0].lower(), parts[-1].lower()}:
                if len(tok) < 3 or tok in consumed_by_account:
                    continue
                if re.search(rf"\b{re.escape(tok)}\b", low):
                    by_token.setdefault(tok, {})[p["person_id"]] = p
        for tok, cands in by_token.items():
            people = list(cands.values())
            if len(people) == 1:
                out["people"].append(Mention("person", people[0], tok))
            else:
                out["ambiguous"][tok] = [Mention("person", c, tok) for c in people]
    _ = named_people

    # events: score by token overlap with the event name; ambiguity when tied
    qtok = set(_tokens(text))
    scored = []
    for e in store.tables["events"]:
        etok = set(_tokens(e["event_name"]))
        hits = qtok & etok
        # require at least a city/type anchor plus one more word, or full-name hit
        if e["event_name"].lower() in low:
            scored.append((99, e))
        elif len(hits) >= 2:
            scored.append((len(hits), e))
    if scored:
        best = max(s for s, _ in scored)
        top = [e for s, e in scored if s == best]
        if len(top) == 1:
            out["events"].append(Mention("event", top[0], top[0]["event_name"]))
        else:
            out["ambiguous"]["event"] = [Mention("event", e, e["event_name"]) for e in top]

    return out


# ------------------------------------------------------------------ intent
INTENTS = ("session_note", "contact", "relationships", "profile",
           "attendance", "prep", "thematic")


def detect_intent(text: str) -> str:
    t = text.lower()
    if t.startswith("note:") or "voice note" in t or "session note" in t \
            or "add a note" in t or "session-update" in t or "log a note" in t:
        return "session_note"
    if "contact detail" in t or "phone" in t or "email" in t \
            or "who should i contact" in t or "contact for" in t or "reach out" in t:
        return "contact"
    if "knows" in t or "who potentially" in t or "connection" in t or "introduc" in t:
        return "relationships"
    # "who is X" / "who's X" — a profile lookup, not a thematic search.
    # Checked after contact/relationships so "who should I contact" and
    # "who potentially knows" keep their own handlers.
    if ("what do we know" in t or "tell me about" in t or "everything about" in t
            or re.search(r"\bwho(\s+is|\s+are|\s+was|\s+were|'s)\b", t)
            or re.search(r"\b(profile|background|bio) (of|for|on)\b", t)):
        return "profile"
    # "prep" must mean call preparation — not "preparing for a sale"
    if ("call prep" in t or "prep call" in t or "prep notes" in t
            or "call notes" in t or "briefing for" in t
            or re.search(r"prep(are)?\b[^.]*\b(call|meeting|conversation)\b", t)):
        return "prep"
    if "attend" in t or "rsvp" in t or "guest" in t or "going to" in t \
            or "involved in" in t or "recent activity" in t or "show" in t and "activity" in t:
        return "attendance"
    return "thematic"


PRONOUNS = re.compile(r"\b(their|them|they|her|his|him|she|he|that (person|account|event|company))\b")


def has_pronoun_reference(text: str) -> bool:
    return bool(PRONOUNS.search(text.lower()))
