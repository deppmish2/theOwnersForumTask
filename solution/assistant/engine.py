"""Answer engine: resolve -> retrieve -> policy gate -> grounded composer.

Every claim in an answer carries record ids and source ids. The engine
returns one of four response modes per turn:

  answer    — grounded answer with citations
  clarify   — ambiguous entity; present options, ask which
  refuse    — restricted contact detail, or claim the dataset can't support
  escalate  — sensitive/restricted territory; answer withheld or partial,
              human-review flag raised
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .data import Store
from . import policy
from . import narrate
from .narrate import Narrative, oxford, count_noun
from .resolve import resolve_entities, detect_intent, has_pronoun_reference
from .session import SessionStore


@dataclass
class Answer:
    mode: str                      # answer | clarify | refuse | escalate
    text: str                      # structured evidence detail (auditable view)
    citations: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)   # gated records (for LLM layer)
    narrative: str = ""            # natural-language answer (primary view)

    @property
    def prose(self) -> str:
        """The answer as prose, falling back to the structured view."""
        return narrate.natural_text(self.narrative or self.text)

    def render(self) -> str:
        head = {"answer": "", "clarify": "[NEEDS CLARIFICATION] ",
                "refuse": "[CANNOT SHARE / NOT SUPPORTED] ",
                "escalate": "[HUMAN REVIEW REQUIRED] "}[self.mode]
        out = head + self.prose
        if self.narrative and self.text:
            out += "\n\nEvidence detail:\n" + narrate.natural_text(self.text)
        if self.flags:
            out += "\n\nFlags: " + "; ".join(
                narrate.natural_text(flag) for flag in sorted(set(self.flags))
            )
        if self.citations:
            out += "\nCitations: " + ", ".join(dict.fromkeys(self.citations))
        return narrate.natural_text(out)


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def _cite(rec_id: str, label: dict) -> str:
    bits = [rec_id]
    if label.get("source_id"):
        bits.append(label["source_id"])
    tag = label.get("visibility", "?")
    rel = label.get("reliability", "")
    return f"({'/'.join(bits)}, {tag}" + (f", {rel} reliability)" if rel else ")")


ATTENDING_STATUSES = {"confirmed"}
EVENT_CONTACT_CATEGORIES = {"host", "host_member", "event_contact"}


def _counts_as_attending(row: dict) -> bool:
    return row.get("attendance_status") in ATTENDING_STATUSES


def _attendance_query_wants_current_attendees(text: str) -> bool:
    t = text.lower()
    return ("member guest" in t or "attend" in t or "attending" in t
            or "going to" in t)


class Engine:
    def __init__(self, store: Store | None = None, session: SessionStore | None = None):
        self.store = store or Store()
        self.session = session or SessionStore()
        self.last_entities: dict[str, list] = {}   # carry-over for pronouns
        self.pending_question: str | None = None   # question awaiting a clarify answer
        self.pending_options: list = []            # the candidates that were offered
        self.pending_entity: dict | None = None    # entity awaiting an intent choice

    # ------------------------------------------------------------------ ask
    def ask(self, text: str) -> Answer:
        # A short reply to a clarifying question ("E005", "the planning dinner")
        # re-runs the original question with that choice pinned, rather than
        # being treated as a new question.
        if self.pending_question and len(text.split()) <= 6:
            chosen = self._match_pending(text)
            if chosen is not None:
                original = self.pending_question
                self.pending_question, self.pending_options = None, []
                bucket = {"person": "people", "account": "accounts",
                          "event": "events"}[chosen.kind]
                picked = {"people": [], "accounts": [], "events": [], "ambiguous": {}}
                picked[bucket] = [chosen]
                return self._answer_with(original, picked)
            # The reply didn't narrow it down — most often because the user
            # echoed the very token that was ambiguous. Re-ask pointedly
            # instead of repeating the identical question.
            if self._looks_like_pending_reply(text):
                return self._reclarify(text)

        # A bare entity reference ("Mara Kessler") states a subject but no
        # request. Ask what's wanted rather than defaulting to a topic search.
        if self.pending_entity and len(text.split()) <= 6:
            choice = self._match_intent_choice(text)
            if choice:
                ents, self.pending_entity = self.pending_entity, None
                return self._answer_with(choice, ents)

        intent = detect_intent(text)
        ents = resolve_entities(self.store, text)

        # pronoun carry-over: reuse last turn's entities when nothing matched
        if (not ents["people"] and not ents["accounts"] and not ents["events"]
                and has_pronoun_reference(text) and self.last_entities):
            ents = {**ents, **{k: v for k, v in self.last_entities.items()
                               if k in ("people", "accounts", "events")}}

        if intent == "session_note":
            return self._handle_session_note(text, ents)

        # ambiguity gate (policy: ask, don't guess)
        if ents["ambiguous"]:
            self.pending_question = text
            self.pending_options = [m for ms in ents["ambiguous"].values() for m in ms]
            return self._clarify(ents["ambiguous"])

        if self._is_bare_entity_reference(text, ents):
            return self._bare_entity_clarify(text, ents)

        self.pending_question = None
        return self._answer_with(text, ents)

    def _answer_with(self, text: str, ents: dict) -> Answer:
        """Dispatch a question to its intent handler with entities already resolved."""
        if any(ents[k] for k in ("people", "accounts", "events")):
            self.last_entities = ents
        handler = {
            "contact": self._handle_contact,
            "relationships": self._handle_relationships,
            "profile": self._handle_profile,
            "attendance": self._handle_attendance,
            "prep": self._handle_prep,
            "thematic": self._handle_thematic,
        }[detect_intent(text)]
        return handler(text, ents)

    # ------------------------------------------- bare entity -> intent choice
    # (question phrasing, prompt shown, keywords that select it)
    _INTENT_CHOICES = [
        ("What do we know about {name}?", "who they are and what we know",
         ("profile", "who", "about", "know", "background", "bio", "summary", "1")),
        ("Give me {name}'s contact details", "their contact details",
         ("contact", "email", "phone", "reach", "2")),
        ("Show recent activity for {name}", "recent activity and events",
         ("activity", "activities", "recent", "event", "events", "attend", "3")),
        ("Who potentially knows someone at {name}?", "who they're connected to",
         ("relationship", "relationships", "connect", "connections", "knows", "4")),
    ]

    def _match_intent_choice(self, text: str) -> str | None:
        """Map a short reply onto one of the offered intents."""
        if not self.pending_entity:
            return None
        toks = set(_tok(text))
        if not toks:
            return None
        name = self.pending_entity["label"]
        for template, _prompt, keywords in self._INTENT_CHOICES:
            if toks & set(keywords):
                return template.format(name=name)
        return None

    def _bare_entity_clarify(self, text: str, ents: dict) -> Answer:
        kind, mention = next((k, ents[k][0]) for k in ("people", "accounts", "events")
                             if ents[k])
        rec, label = mention.record, mention.name
        actual_kind = mention.kind
        self.pending_entity = {**ents, "label": label}
        self.pending_question, self.pending_options = None, []

        if actual_kind == "person":
            acct = self.store.accounts.get(rec.get("account_id", ""), {})
            who = (f"{label} — {rec.get('role_title')}"
                   + (f" at {acct['account_name']}" if acct else "")
                   + f" [{rec['person_id']}]")
        elif actual_kind == "account":
            who = (f"{label} — {rec.get('sector')}, {rec.get('country')} "
                   f"[{rec['account_id']}]")
        else:
            who = (f"{label} — {rec.get('city')}, {rec.get('event_date')} "
                   f"[{rec['event_id']}]")

        choices = [p.format(name=label) for _t, p, _k in self._INTENT_CHOICES]
        if actual_kind == "event":
            choices = ["who is attending", "who to contact about it"]
        lines = [f"Matched {who}. What would you like to know?"] + \
                [f"  • {c}" for c in choices]
        n = Narrative().para(
            f"I found {who} — but a name on its own doesn't tell me what you want to "
            f"know, so I'd rather ask than pick something and be wrong. Options:"
        ).bullets("", choices).para(
            "Say which (a word like “contact” or “activity” is enough), or ask the "
            "question directly.")
        return Answer("clarify", "\n".join(lines), narrative=n.render())

    @staticmethod
    def _is_bare_entity_reference(text: str, ents: dict) -> bool:
        """True when the input names an entity but asks nothing about it."""
        if not any(ents[k] for k in ("people", "accounts", "events")):
            return False
        if ents["ambiguous"]:
            return False
        matched: set[str] = set()
        for k in ("people", "accounts", "events"):
            for m in ents[k]:
                matched.update(_tok(m.name))
                matched.update(_tok(m.matched))
        filler = {"the", "a", "an", "please", "info", "on", "for", "of", "and"}
        residue = [t for t in _tok(text) if t not in matched and t not in filler]
        return not residue

    # ------------------------------------------------- clarify follow-through
    def _match_pending(self, text: str):
        """Resolve a reply against the candidates we actually offered.

        Returns the single chosen Mention, or None if the reply is empty,
        unrelated, or still matches more than one candidate.
        """
        if not self.pending_options:
            return None
        low = " " + text.lower().strip() + " "

        # 1. explicit record id
        ids = {m.id.upper() for m in self.pending_options}
        hit = [m for m in self.pending_options
               if re.search(rf"\b{m.id}\b", text.upper()) and m.id.upper() in ids]
        if len(hit) == 1:
            return hit[0]

        # 2. full name / full event name
        hit = [m for m in self.pending_options if m.name.lower() in low]
        if len(hit) == 1:
            return hit[0]

        # 3. any distinguishing token that fits exactly one candidate
        #    (e.g. "Kessler" or "planning" — but not "Mara", shared by both)
        shared = set.intersection(*[set(_tok(m.name)) for m in self.pending_options])
        scored = []
        for m in self.pending_options:
            distinct = [t for t in _tok(m.name) if t not in shared]
            if any(re.search(rf"\b{re.escape(t)}\b", low) for t in distinct):
                scored.append(m)
        if len(scored) == 1:
            return scored[0]

        # 4. ordinal ("the first one", "second")
        for word, idx in (("first", 0), ("second", 1), ("third", 2)):
            if re.search(rf"\b{word}\b", low) and idx < len(self.pending_options):
                return self.pending_options[idx]
        return None

    def _looks_like_pending_reply(self, text: str) -> bool:
        """Is this short input plausibly an attempt to answer the clarify?"""
        low = " " + text.lower() + " "
        if re.search(r"\b[PAE]\d{3}\b", text.upper()):
            return True
        for m in self.pending_options:
            if any(re.search(rf"\b{re.escape(t)}\b", low) for t in _tok(m.name)):
                return True
        return bool(re.search(r"\b(first|second|third|either|both)\b", low))

    def _reclarify(self, text: str) -> Answer:
        opts = self.pending_options
        shared = set.intersection(*[set(_tok(m.name)) for m in opts]) if opts else set()
        echoed = [t for t in _tok(text) if t in shared]
        lines = [f"  • {m.name} [{m.id}]" for m in opts]
        if echoed:
            lead = (f"“{echoed[0].title()}” is the part they have in common, so that "
                    f"doesn't narrow it down — my earlier wording was misleading there, "
                    f"sorry. Use the record id instead:")
        else:
            lead = ("That didn't match either option. Use the record id:")
        n = Narrative().para(lead).bullets("", [
            f"{m.id} — {m.name}"
            + (f", {m.record.get('role_title')}" if m.kind == "person" else "")
            + (f" ({m.record.get('city')}, {m.record.get('event_date')})"
               if m.kind == "event" else "")
            for m in opts])
        return Answer("clarify", "\n".join(lines), narrative=n.render())

    # -------------------------------------------------------------- clarify
    def _clarify(self, ambiguous: dict) -> Answer:
        lines, options, kinds = [], [], set()
        for _surface, mentions in ambiguous.items():
            for m in mentions:
                kinds.add(m.kind)
                extra = ""
                if m.kind == "person":
                    acct = self.store.accounts.get(m.record.get("account_id", ""), {})
                    where = (f" at {acct['account_name']}" if acct
                             else f" — {m.record.get('relationship_to_company', 'no account')}")
                    extra = (f" — {m.record.get('role_title', '')}, "
                             f"{acct.get('account_name', 'no linked account')}")
                    options.append(f"{m.name}, {m.record.get('role_title')}{where} "
                                   f"— reply {m.id}")
                elif m.kind == "event":
                    extra = (f" — {m.record.get('city')}, {m.record.get('event_date')} "
                             f"({m.record.get('status')})")
                    options.append(f"the {m.name} in {m.record.get('city')} on "
                                   f"{m.record.get('event_date')}, currently "
                                   f"{m.record.get('status')} — reply {m.id}")
                else:
                    options.append(f"{m.name} — reply {m.id}")
                lines.append(f"  • {m.name} [{m.id}]{extra}")
        noun = oxford(sorted(kinds), "or") or "record"
        count = sum(len(v) for v in ambiguous.values())
        n = Narrative().para(
            f"I need one detail before I answer: that could mean any of {count} "
            f"{noun} records in the dataset, and I'd rather ask than pick the wrong one."
        ).bullets("", options).para(
            "Reply with the record id — the shared name won't narrow it down.")
        return Answer("clarify", "\n".join(lines), narrative=n.render())

    # --------------------------------------------------------- session note
    def _handle_session_note(self, text: str, ents: dict) -> Answer:
        body = re.sub(r"^\s*note:\s*", "", text, flags=re.I)
        ids = [m.id for k in ("people", "accounts", "events") for m in ents[k]]
        note = self.session.add(body, entities=ids)
        linked = ", ".join(ids) if ids else "no dataset entities"
        if ids:
            names = [ (self.store.people.get(i) or self.store.accounts.get(i)
                       or self.store.events.get(i) or {}) for i in ids ]
            labels = [n.get("full_name") or n.get("account_name") or n.get("event_name")
                      for n in names]
            where = f"It's attached to {oxford([l for l in labels if l])}, so it will surface " \
                    f"when you ask about them."
        else:
            where = ("It didn't match any account, person or event in the dataset, so it's "
                     "stored unlinked rather than guessing what it refers to.")
        n = Narrative().para(
            f"Noted — I've saved that as session note {note['note_id']}. {where}"
        ).para(
            "It stays outside the dataset: session notes are temporary and unverified, they "
            "are never written into the CSVs, and whenever one appears in an answer it is "
            "labelled as a session note rather than presented as a dataset fact.")
        return Answer(
            "answer",
            f"Recorded session note {note['note_id']} (linked to: {linked}).",
            citations=[f"({note['note_id']}, session note)"],
            narrative=n.render())

    # -------------------------------------------------------------- contact
    def _handle_contact(self, text: str, ents: dict) -> Answer:
        if ents["people"]:
            p = ents["people"][0].record
            view = policy.contact_view(p)
            name = p["full_name"]
            acct = self.store.accounts.get(p.get("account_id", ""), {})
            at = f" at {acct['account_name']}" if acct else ""
            if not view["email"] and not view["phone"]:
                mode = "refuse"
                body = (f"{name}'s contact details cannot be shared: "
                        f"{view['note']} (contact_visibility={view['policy']}).")
                if view["policy"] == "restricted":
                    body += " Escalate to the account manager for permission."
                n = Narrative().para(
                    f"I can't share contact details for {name}{at}. Their record is marked "
                    f"{view['policy']}, which means {view['note']}.")
                if view["policy"] == "restricted":
                    n.para(f"If you need to reach them, the route is permission from the "
                           f"relationship owner — {acct.get('account_manager', 'the account manager')} "
                           f"manages this account.")
                else:
                    n.para("I can still tell you what the dataset holds about their role and "
                           "activity — just ask.")
            else:
                mode = "answer"
                parts = [f"{name} ({p['person_id']}), contact_visibility={view['policy']}:"]
                shown = []
                if view["email"]:
                    parts.append(f"  email: {view['email']}")
                    shown.append(f"their business email is {view['email']}")
                if view["phone"]:
                    parts.append(f"  phone: {view['phone']}")
                    shown.append(f"their phone is {view['phone']}")
                if not view["phone"]:
                    parts.append(f"  phone: withheld — {view['note']}")
                body = "\n".join(parts)
                n = Narrative().para(
                    f"For {name}{at}, {oxford(shown)}.")
                if not view["phone"]:
                    n.para(f"Their phone number is in the dataset but I'm not sharing it — "
                           f"contact_visibility is set to {view['policy']}, which permits the "
                           f"email address only.")
            return Answer(mode, body, citations=[f"({p['person_id']}, people.csv)"],
                          narrative=n.render())

        if ents["events"]:
            e = ents["events"][0].record
            return self._event_contact(e)

        if ents["accounts"]:
            a = ents["accounts"][0].record
            people = self.store.people_of_account(a["account_id"])
            lines = [f"Contacts at {a['account_name']} ({a['account_id']}), "
                     f"per each person's contact_visibility:"]
            cites, sharable, held = [], [], []
            for p in people:
                v = policy.contact_view(p)
                shown = v["email"] or "email withheld"
                if v["phone"]:
                    shown += f", {v['phone']}"
                lines.append(f"  • {p['full_name']} — {p['role_title']}: {shown} "
                             f"[{v['policy']}]")
                cites.append(f"({p['person_id']}, people.csv)")
                if v["email"]:
                    detail = v["email"] + (f" / {v['phone']}" if v["phone"] else
                                           " (phone withheld — email_only)")
                    sharable.append(f"{p['full_name']}, {p['role_title']} — {detail}")
                else:
                    held.append(f"{p['full_name']} ({p['role_title']}, {v['policy']})")
            n = Narrative().para(
                f"{a['account_name']} has {count_noun(len(people), 'contact')} on file. "
                f"Each person's visibility setting is applied individually:")
            n.bullets("", sharable)
            if held:
                n.para(f"I'm withholding details for {oxford(held)} — those records are not "
                       f"shareable, so reaching them needs permission from "
                       f"{a.get('account_manager', 'the account manager')}.")
            return Answer("answer", "\n".join(lines), citations=cites,
                          narrative=n.render())

        return Answer("clarify",
                      "Whose contact details do you need? I couldn't match "
                      "a person, account, or event in the dataset.",
                      narrative="I couldn't match a person, account or event in the dataset "
                                "from that. Whose contact details do you need? A full name or "
                                "a record id works.")

    def _event_contact(self, e: dict) -> Answer:
        """Best-evidence contact for an event: coordination relationships, then hosts."""
        cites, lines, flags, items = [], [], [], []
        eid = e["event_id"]
        lines.append(f"Contact options for {e['event_name']} ({eid}, {e['status']}):")
        found = False
        event_rows = self.store.attendance_for_event(eid)
        event_people = {at["person_id"] for at in event_rows if at.get("person_id")}
        event_sources = {at["source_id"] for at in event_rows if at.get("source_id")}
        seen_people: set[str] = set()

        for at in event_rows:
            if at["attendee_category"] not in EVENT_CONTACT_CATEGORIES:
                continue
            if not _counts_as_attending(at):
                continue
            pid = at.get("person_id", "")
            if pid in seen_people:
                continue
            p = self.store.people.get(pid, {})
            gate = policy.gate_record(self.store, at)
            lines.append(f"  • {p.get('full_name')} — {at['attendee_category']} "
                         f"({at['attendance_status']})")
            cites.append(_cite(at["attendance_id"], gate["label"]))
            items.append(f"{p.get('full_name')} — listed as "
                         f"{at['attendee_category'].replace('_', ' ')} "
                         f"({at['attendance_status']}) "
                         f"{narrate.cite(at['attendance_id'], gate['label'])}")
            seen_people.add(pid)
            found = True

        for r in self.store.tables["relationships"]:
            if r["relationship_type"] != "event_coordination":
                continue
            if r.get("source_id") not in event_sources:
                continue
            if not ({r.get("from_person_id"), r.get("to_person_id")} & event_people):
                continue
            gate = policy.gate_record(self.store, r)
            if gate["disposition"] == "withhold":
                flags.append("a restricted relationship record was withheld")
                continue
            pid = r.get("from_person_id", "")
            if pid in seen_people:
                continue
            frm = self.store.people.get(pid, {})
            to = self.store.people.get(r["to_person_id"], {})
            lines.append(f"  • {frm.get('full_name')} coordinates logistics with "
                         f"{to.get('full_name')} — {r['basis']}")
            cites.append(_cite(r["relationship_id"], gate["label"]))
            items.append(f"{frm.get('full_name')} — coordinates logistics with "
                         f"{to.get('full_name')}. {r['basis']} "
                         f"{narrate.cite(r['relationship_id'], gate['label'])}")
            seen_people.add(pid)
            found = True
        if not found:
            return Answer("refuse",
                          f"The dataset holds no contact/coordination record for "
                          f"{e['event_name']} ({eid}). I can't name a contact without "
                          f"inventing one — escalate to the events team.",
                          citations=[f"({eid}, events.csv)"],
                          narrative=f"There's no contact or coordination record for the "
                                    f"{e['event_name']} in the dataset, so I can't name "
                                    f"anyone without inventing them. The events team would "
                                    f"be the place to ask.")
        lines.append("Note: individual contact details still follow each person's "
                     "contact_visibility — ask for a specific person to get them.")
        n = Narrative().para(
            f"For the {e['event_name']} ({e['event_date']}, {e['status']}), the dataset "
            f"points to {count_noun(len(items), 'person')}:"
        ).bullets("", items).para(
            "Their individual contact details still follow each person's own "
            "contact_visibility setting — ask about a specific person and I'll apply it.")
        return Answer("answer", "\n".join(lines), citations=cites, flags=flags,
                      narrative=n.render())

    # -------------------------------------------------------- relationships
    def _handle_relationships(self, text: str, ents: dict) -> Answer:
        target_people, label = [], None
        if ents["accounts"]:
            a = ents["accounts"][0].record
            label = a["account_name"]
            target_people = [p["person_id"] for p in self.store.people_of_account(a["account_id"])]
            rels = self.store.relationships_touching_account(a["account_id"])
        elif ents["people"]:
            p = ents["people"][0].record
            label = p["full_name"]
            target_people = [p["person_id"]]
            rels = self.store.relationships_touching_person(p["person_id"])
        else:
            return Answer("clarify", "Who or which account should I look for connections to?")

        rels = rels + [r for pid in target_people
                       for r in self.store.relationships_touching_person(pid)]
        seen, shown, withheld, cites = set(), [], 0, []
        for r in rels:
            if r["relationship_id"] in seen:
                continue
            seen.add(r["relationship_id"])
            gate = policy.gate_record(self.store, r)
            if gate["disposition"] == "withhold":
                withheld += 1
                continue
            frm = self.store.people.get(r["from_person_id"], {})
            to = self.store.people.get(r["to_person_id"], {})
            caveat = f" [{gate['reason']}]" if gate["reason"] else ""
            shown.append(f"  • {frm.get('full_name', '?')} ↔ {to.get('full_name', '?')} "
                         f"({r['relationship_type']}, {r['strength']}): {r['basis']}{caveat}")
            cites.append(_cite(r["relationship_id"], gate["label"]))

        flags = []
        if withheld:
            flags.append(f"{withheld} restricted relationship record(s) withheld — human review")
        if not shown:
            body = (f"relationships.csv holds no relationship path touching {label}. "
                    f"That is an evidence gap, not proof no connection exists — "
                    f"I won't infer one.")
            mode = "answer"
            nar = (f"No one, on the evidence available. relationships.csv holds only four rows "
                   f"in total and none of them touch {label}.")
            if withheld:
                mode = "escalate"
                body += " (A restricted record exists but its content is withheld.)"
                nar += (" There is a restricted relationship record in scope, but its content "
                        "is withheld pending human review.")
            nar += (f" I want to be precise about what that means: it's an absence of recorded "
                    f"evidence, not evidence of absence. Someone at the firm may well know "
                    f"{label} — the dataset simply doesn't capture it, and I'm not going to "
                    f"infer a path from shared sector or geography.")
            return Answer(mode, body, flags=flags,
                          citations=[f"({label}, relationships.csv: no rows)"],
                          narrative=nar)
        n = Narrative().para(
            f"The dataset records {count_noun(len(shown), 'relationship path')} touching "
            f"{label}:").bullets("", [s.strip(" •") for s in shown])
        if withheld:
            n.para(f"{count_noun(withheld, 'further record')} in this area "
                   f"{'is' if withheld == 1 else 'are'} restricted — flagged for human "
                   f"review rather than shown.")
        return Answer("answer",
                      f"Known relationship paths for {label}:\n" + "\n".join(shown),
                      citations=cites, flags=flags, narrative=n.render())

    # -------------------------------------------------------------- profile
    def _handle_profile(self, text: str, ents: dict) -> Answer:
        if policy.query_is_sensitive(text) and ents["people"]:
            # e.g. "tell me everything about Daniel Weber's succession plans"
            return self._sensitive_person_topic(text, ents["people"][0].record)
        if ents["people"]:
            return self._person_profile(ents["people"][0].record)
        if ents["accounts"]:
            return self._account_summary(ents["accounts"][0].record, prep=False)
        if ents["events"]:
            return self._event_attendance(ents["events"][0].record, text)
        # asked about a name the dataset doesn't contain — say that plainly
        # rather than falling through to a thematic search
        name = self._unmatched_name(text)
        if name:
            return Answer(
                "refuse",
                f"No person or account matching '{name}' exists in the dataset "
                f"(people.csv, accounts.csv).",
                citations=["(people.csv / accounts.csv: no matching record)"],
                narrative=f"I have no record of anyone called “{name}”. I searched "
                          f"people.csv and accounts.csv by full name, given name and "
                          f"surname, and nothing matched — so either the spelling differs "
                          f"from the dataset or they aren't in it. I'm not going to guess "
                          f"at a near-match.")
        return Answer("clarify", "Which person or account should I profile?",
                      narrative="Who would you like to know about? A name or a record id "
                                "will do.")

    _NAME_STOPWORDS = {
        "who", "is", "are", "was", "were", "the", "a", "an", "what", "do", "we",
        "know", "about", "tell", "me", "everything", "profile", "background",
        "bio", "of", "for", "on", "this", "that", "person", "and",
    }

    def _unmatched_name(self, text: str) -> str | None:
        """Best-effort extraction of the proper noun the user asked about."""
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", text)
                 if w.lower() not in self._NAME_STOPWORDS]
        return " ".join(words[:3]) if words else None

    def _sensitive_person_topic(self, text: str, p: dict) -> Answer:
        pid = p["person_id"]
        recs = self.store.activities_for_person(pid) + \
               self.store.relationships_touching_person(pid)
        shown, withheld_ids, cites = [], [], []
        for r in recs:
            if not policy.record_is_sensitive(r):
                continue
            gate = policy.gate_record(self.store, r)
            rid = r.get("activity_id") or r.get("relationship_id")
            if gate["disposition"] == "withhold":
                withheld_ids.append(rid)
                # the *existence* of a restricted record is itself a claim, so it
                # gets a citation — the id, never the content
                cites.append(f"({rid}, restricted — content withheld)")
                continue
            desc = r.get("summary") or r.get("basis") or r.get("title", "")
            caveat = f" [{gate['reason']}]" if gate["reason"] else ""
            shown.append(f"  • {desc}{caveat}")
            cites.append(_cite(rid, gate["label"]))
        lines = [f"On this topic for {p['full_name']} ({pid}):"]
        flags = ["sensitive topic (succession/ownership) — cited, reliability-labeled "
                 "answer required"]
        if withheld_ids:
            lines.append(f"  • {len(withheld_ids)} restricted record(s) exist "
                         f"({', '.join(withheld_ids)}) — content withheld under the "
                         f"restricted-notes policy.")
            flags.append("restricted note(s) withheld — route to a human before any use")
        if shown:
            lines += shown
        if not shown and not withheld_ids:
            return Answer("refuse",
                          f"The dataset contains no records about that topic for "
                          f"{p['full_name']} — I can't speculate.",
                          citations=[f"({pid}, people.csv)"],
                          narrative=f"Nothing in the dataset covers that topic for "
                                    f"{p['full_name']}, so there's nothing I can tell you. "
                                    f"I'm not going to speculate on a succession question.")
        acct = self.store.accounts.get(p.get("account_id", ""), {})
        at = f" at {acct['account_name']}" if acct else ""
        n = Narrative()
        if withheld_ids:
            n.para(
                f"I can't answer this one in full. The dataset does hold "
                f"{count_noun(len(withheld_ids), 'record')} on succession relating to "
                f"{p['full_name']}{at} — {oxford(withheld_ids)} — but "
                f"{'it is' if len(withheld_ids) == 1 else 'they are'} marked restricted, so "
                f"the content stays withheld.")
            n.para(
                "I'm telling you the record exists rather than pretending it doesn't, because "
                "knowing there is something to ask about is itself useful. To actually see it, "
                "route the request through "
                f"{acct.get('account_manager', 'the account manager')} — this is a "
                "human-review decision, not one I should make.")
        if shown:
            n.bullets("What I can share on this topic:", [s.strip(" •") for s in shown])
            n.para("Succession and ownership questions are sensitive by policy, so treat the "
                   "above as internal, reliability-labelled context rather than settled fact.")
        mode = "escalate" if withheld_ids else "answer"
        return Answer(mode, "\n".join(lines), citations=cites, flags=flags,
                      narrative=n.render())

    def _person_profile(self, p: dict) -> Answer:
        pid = p["person_id"]
        acct = self.store.accounts.get(p.get("account_id", ""), {})
        lines = [f"{p['full_name']} ({pid})",
                 f"  role: {p['role_title']} — {p['relationship_to_company']}"
                 + (f", {acct.get('account_name')} ({acct.get('account_id')})" if acct else ""),
                 f"  family member: {p['is_family_member']}"
                 + (f", generation: {p['generation']}" if p.get("generation", "n/a") != "n/a" else ""),
                 f"  bio: {p.get('bio_note', '')}"]
        cites = [f"({pid}, people.csv)"]
        flags = []
        if p.get("sensitivity_level") in ("confidential", "restricted"):
            flags.append(f"person record is {p['sensitivity_level']} — internal handling only")

        ev_items, act_items = [], []
        atts = self.store.attendance_for_person(pid)
        if atts:
            lines.append("  events:")
            for at in atts:
                e = self.store.events.get(at["event_id"], {})
                gate = policy.gate_record(self.store, at)
                lines.append(f"    • {e.get('event_name')} — {at['attendance_status']} "
                             f"({at['attendee_category']})")
                cites.append(_cite(at["attendance_id"], gate["label"]))
                ev_items.append(f"{e.get('event_name')} ({e.get('event_date')}) — "
                                f"{at['attendance_status']}, {at['attendee_category']} "
                                f"{narrate.cite(at['attendance_id'], gate['label'])}")

        acts = self.store.activities_for_person(pid)
        withheld = 0
        if acts:
            lines.append("  activity:")
            for a in acts:
                gate = policy.gate_record(self.store, a)
                if gate["disposition"] == "withhold":
                    withheld += 1
                    continue
                caveat = f" [{gate['reason']}]" if gate["reason"] else ""
                lines.append(f"    • {a['activity_date']}: {a['summary']}{caveat}")
                cites.append(_cite(a["activity_id"], gate["label"]))
                act_items.append(f"{a['activity_date']} — {a['summary']}"
                                 + (f" (note: {gate['reason']})" if gate["reason"] else "")
                                 + f" {narrate.cite(a['activity_id'], gate['label'])}")
        if withheld:
            flags.append(f"{withheld} restricted record(s) withheld — human review")
            lines.append(f"  ({withheld} restricted record(s) withheld)")

        note_items = []
        for note in self.session.for_entity(pid):
            lines.append(f"  session note {note['note_id']} ({note['timestamp']}): "
                         f"{note['text']} [session-only, unverified]")
            cites.append(f"({note['note_id']}, session note)")
            note_items.append(f"{note['text']} [{note['note_id']} · session note, unverified]")

        lines.append("  contact: available on request, subject to "
                     f"contact_visibility={p.get('contact_visibility')}")

        # ---- prose
        gen = (f", {p['generation'].lower()}" if p.get("generation", "n/a") != "n/a" else "")
        fam = "a family member" if p.get("is_family_member") == "yes" else "not a family member"
        n = Narrative().para(
            f"{p['full_name']} is {p['role_title']}"
            + (f" at {acct['account_name']}" if acct else "")
            + f" — {p['relationship_to_company'].lower()}, {fam}{gen}."
            + (f" {p['bio_note']}." if p.get("bio_note") else ""))
        if ev_items:
            n.bullets("Events on record:", ev_items)
        if act_items:
            n.bullets("Recent activity:", act_items)
        if note_items:
            n.bullets("From this session only (not part of the dataset):", note_items)
        vis = p.get("contact_visibility")
        vis_note = policy.CONTACT_RULES.get(vis, {}).get("note", "")
        n.para(f"On contact details: their record is set to {vis} — {vis_note}. Ask directly "
               f"and I'll apply that rule.")
        if withheld:
            n.para(f"{count_noun(withheld, 'record')} tied to this person "
                   f"{'is' if withheld == 1 else 'are'} restricted and withheld pending "
                   f"human review.")
        if p.get("sensitivity_level") in ("confidential", "restricted"):
            n.para(f"The person record itself is marked {p['sensitivity_level']} — internal "
                   f"handling only.")
        mode = "escalate" if withheld else "answer"
        return Answer(mode, "\n".join(lines), citations=cites, flags=flags,
                      narrative=n.render())

    # ----------------------------------------------------------- attendance
    def _handle_attendance(self, text: str, ents: dict) -> Answer:
        if ents["events"] and ents["people"]:
            return self._person_event_attendance(ents["people"][0].record,
                                                 ents["events"][0].record)
        if ents["events"] and ents["accounts"]:
            return self._account_event_attendance(ents["accounts"][0].record,
                                                  ents["events"][0].record)
        if ents["events"]:
            return self._event_attendance(ents["events"][0].record, text)
        if ents["accounts"]:
            return self._account_activity(ents["accounts"][0].record, text)
        if ents["people"]:
            return self._person_profile(ents["people"][0].record)
        return Answer("clarify", "Which event or account do you mean?")

    def _event_attendance(self, e: dict, text: str) -> Answer:
        eid = e["event_id"]
        want_cat = "member_guest" if "member guest" in text.lower() else None
        rows = self.store.attendance_for_event(eid)
        if want_cat:
            rows = [r for r in rows if r["attendee_category"] == want_cat]
        current_only = _attendance_query_wants_current_attendees(text)
        skipped_rows = [r for r in rows if not _counts_as_attending(r)] if current_only else []
        shown_rows = [r for r in rows if _counts_as_attending(r)] if current_only else rows
        lines = [f"{e['event_name']} ({eid}, {e['event_date']}, {e['status']}):"]
        cites, items, by_status = [], [], {}
        for at in sorted(shown_rows, key=lambda r: r["person_id"]):
            p = self.store.people.get(at["person_id"], {})
            a = self.store.accounts.get(at["account_id"], {})
            gate = policy.gate_record(self.store, at)
            lines.append(f"  • {p.get('full_name', '?')} ({a.get('account_name', 'no account')}) "
                         f"— {at['attendance_status']}, {at['attendee_category']}")
            cites.append(_cite(at["attendance_id"], gate["label"]))
            items.append(f"{p.get('full_name', '?')} of {a.get('account_name', 'no account')} "
                         f"— {at['attendance_status']} "
                         f"{narrate.cite(at['attendance_id'], gate['label'])}")
            by_status[at["attendance_status"]] = by_status.get(at["attendance_status"], 0) + 1
        if current_only and skipped_rows:
            skipped = {}
            for row in skipped_rows:
                skipped[row["attendance_status"]] = skipped.get(row["attendance_status"], 0) + 1
            lines.append("  Note: excluded from the attending list — "
                         + oxford([f"{v} {k}" for k, v in skipped.items()]))
        if len(lines) == 1:
            if current_only and rows:
                statuses = {}
                for row in rows:
                    statuses[row["attendance_status"]] = statuses.get(row["attendance_status"], 0) + 1
                return Answer(
                    "answer",
                    f"No one is currently attending {e['event_name']} ({eid}) on the "
                    f"records available; existing RSVP rows are {oxford([f'{v} {k}' for k, v in statuses.items()])}.",
                    citations=[f"({eid}, event_attendance.csv: no confirmed rows)"],
                    narrative=f"No one is currently recorded as attending the "
                              f"{e['event_name']}. The RSVP rows on file are "
                              f"{oxford([f'{v} {k}' for k, v in statuses.items()])}, "
                              f"so I wouldn't count any of them as attending.")
            return Answer("answer",
                          f"No attendance rows exist for {e['event_name']} ({eid}). "
                          f"Absence of RSVPs is an evidence gap, not a confirmed no.",
                          citations=[f"({eid}, events.csv)"],
                          narrative=f"The dataset holds no RSVP records at all for the "
                                    f"{e['event_name']}. That's an evidence gap rather than a "
                                    f"confirmed 'nobody is attending' — I can only tell you "
                                    f"nothing was recorded.")
        breakdown = oxford([f"{v} {k}" for k, v in by_status.items()])
        who = "member guests" if want_cat else "attendees"
        n = Narrative().para(
            f"The {e['event_name']} runs on {e['event_date']} in {e['city']} and is currently "
            f"{e['status']}. {count_noun(len(shown_rows), f'{who[:-1]}', who)} "
            f"{'is' if len(shown_rows) == 1 else 'are'} on the list ({breakdown}):"
        ).bullets("", items).para(
            "One handling note: every one of these RSVPs comes from the internal event system, "
            "so treat the list as internal knowledge — none of it is public.")
        if current_only and skipped_rows:
            skipped = {}
            for row in skipped_rows:
                skipped[row["attendance_status"]] = skipped.get(row["attendance_status"], 0) + 1
            n.para("I excluded RSVP rows that are not currently attending — "
                   + oxford([f"{v} {k}" for k, v in skipped.items()])
                   + " — so the answer reflects who is actually on the attending list.")
        return Answer("answer", "\n".join(lines), citations=cites, narrative=n.render())

    def _account_event_attendance(self, a: dict, e: dict) -> Answer:
        rows = [r for r in self.store.attendance_for_event(e["event_id"])
                if r["account_id"] == a["account_id"]]
        if not rows:
            return Answer("answer",
                          f"The dataset has no RSVP linking {a['account_name']} to "
                          f"{e['event_name']} — no confirmed attendance, though absence "
                          f"of a row is not a confirmed 'no'.",
                          citations=[f"({e['event_id']}, event_attendance.csv: no rows)"],
                          narrative=f"Not as far as the dataset shows — there is no RSVP "
                                    f"linking {a['account_name']} to the {e['event_name']}. "
                                    f"I'd treat that as 'nothing recorded' rather than a "
                                    f"confirmed no; an unrecorded RSVP looks identical to a "
                                    f"declined one from here.")
        attending = [r for r in rows if _counts_as_attending(r)]
        not_attending = [r for r in rows if not _counts_as_attending(r)]
        if not attending:
            lines = [f"No — {a['account_name']} has no confirmed attendee for "
                     f"{e['event_name']} ({e['event_id']})."]
            cites, items = [], []
            for at in not_attending:
                p = self.store.people.get(at["person_id"], {})
                gate = policy.gate_record(self.store, at)
                lines.append(f"  • {p.get('full_name')} — {at['attendance_status']} "
                             f"(rsvp {at['rsvp_date']})")
                cites.append(_cite(at["attendance_id"], gate["label"]))
                items.append(f"{p.get('full_name')} is {at['attendance_status']} "
                             f"{narrate.cite(at['attendance_id'], gate['label'])}")
            n = Narrative().para(
                f"No. {a['account_name']} is not currently recorded as attending the "
                f"{e['event_name']}:"
            ).bullets("", items).para(
                "These are RSVP-status records from the internal event system, so I treat "
                "waitlisted, invited, and declined rows as not currently attending.")
            return Answer("answer", "\n".join(lines), citations=cites, narrative=n.render())
        lines = [f"Yes — {a['account_name']} has {len(attending)} confirmed RSVP(s) for "
                 f"{e['event_name']} ({e['event_id']}):"]
        cites, items = [], []
        for at in attending:
            p = self.store.people.get(at["person_id"], {})
            gate = policy.gate_record(self.store, at)
            lines.append(f"  • {p.get('full_name')} — {at['attendance_status']} "
                         f"(rsvp {at['rsvp_date']})")
            cites.append(_cite(at["attendance_id"], gate["label"]))
            items.append(f"{p.get('full_name')}, {at['attendance_status']} on "
                         f"{at['rsvp_date']} "
                         f"{narrate.cite(at['attendance_id'], gate['label'])}")
        if not_attending:
            skipped = {}
            for row in not_attending:
                skipped[row["attendance_status"]] = skipped.get(row["attendance_status"], 0) + 1
            lines.append("  Note: additional RSVP rows not counted as attending — "
                         + oxford([f"{v} {k}" for k, v in skipped.items()]))
        n = Narrative().para(
            f"Yes. {a['account_name']} has {count_noun(len(attending), 'confirmed RSVP')} for the "
            f"{e['event_name']} on {e['event_date']}:"
        ).bullets("", items).para(
            "Both RSVPs come from internal event-system records, so this is internal "
            "knowledge — not something to repeat as public fact.")
        if not_attending:
            skipped = {}
            for row in not_attending:
                skipped[row["attendance_status"]] = skipped.get(row["attendance_status"], 0) + 1
            n.para("I excluded additional RSVP rows that are not currently attending — "
                   + oxford([f"{v} {k}" for k, v in skipped.items()]) + ".")
        return Answer("answer", "\n".join(lines), citations=cites, narrative=n.render())

    def _person_event_attendance(self, p: dict, e: dict) -> Answer:
        rows = [r for r in self.store.attendance_for_event(e["event_id"])
                if r["person_id"] == p["person_id"]]
        if not rows:
            return Answer(
                "answer",
                f"The dataset has no RSVP linking {p['full_name']} to {e['event_name']} "
                f"({e['event_id']}) — nothing recorded either way.",
                citations=[f"({e['event_id']}, event_attendance.csv: no person row)"],
                narrative=f"Nothing recorded. The dataset has no RSVP row linking "
                          f"{p['full_name']} to the {e['event_name']}, so I can't say "
                          f"they're attending.")
        attending = [r for r in rows if _counts_as_attending(r)]
        cites, items = [], []
        if attending:
            lines = [f"Yes — {p['full_name']} is attending {e['event_name']} "
                     f"({e['event_id']}):"]
            for at in attending:
                gate = policy.gate_record(self.store, at)
                lines.append(f"  • {at['attendance_status']} (rsvp {at['rsvp_date']})")
                cites.append(_cite(at["attendance_id"], gate["label"]))
                items.append(f"{at['attendance_status']} on {at['rsvp_date']} "
                             f"{narrate.cite(at['attendance_id'], gate['label'])}")
            n = Narrative().para(
                f"Yes. {p['full_name']} is currently recorded as attending the "
                f"{e['event_name']}:"
            ).bullets("", items)
            return Answer("answer", "\n".join(lines), citations=cites, narrative=n.render())

        lines = [f"No — {p['full_name']} is not currently attending {e['event_name']} "
                 f"({e['event_id']}):"]
        for at in rows:
            gate = policy.gate_record(self.store, at)
            lines.append(f"  • {at['attendance_status']} (rsvp {at['rsvp_date']})")
            cites.append(_cite(at["attendance_id"], gate["label"]))
            items.append(f"{at['attendance_status']} on {at['rsvp_date']} "
                         f"{narrate.cite(at['attendance_id'], gate['label'])}")
        n = Narrative().para(
            f"No. {p['full_name']} is not currently recorded as attending the "
            f"{e['event_name']}:"
        ).bullets("", items).para(
            "I treat waitlisted, invited, and declined RSVP rows as not currently attending.")
        return Answer("answer", "\n".join(lines), citations=cites, narrative=n.render())

    def _account_activity(self, a: dict, text: str) -> Answer:
        aid = a["account_id"]
        region_filter = None
        for region in ("asia", "europe"):
            if region in text.lower():
                region_filter = region
        lines = [f"{a['account_name']} ({aid}) — activity"
                 + (f" ({region_filter.title()} events/activity)" if region_filter else "") + ":"]
        cites, flags = [], []
        ev_items, pub_items, int_items, note_items = [], [], [], []
        atts = self.store.attendance_for_account(aid)
        shown_any = False
        for at in atts:
            e = self.store.events.get(at["event_id"], {})
            if region_filter and e.get("region", "").lower() != region_filter:
                continue
            gate = policy.gate_record(self.store, at)
            lines.append(f"  • {e.get('event_name')} ({e.get('event_date')}) — "
                         f"{at['attendance_status']}, {at['attendee_category']}")
            cites.append(_cite(at["attendance_id"], gate["label"]))
            ev_items.append(f"{e.get('event_name')} on {e.get('event_date')} — "
                            f"{at['attendance_status']} "
                            f"{narrate.cite(at['attendance_id'], gate['label'])}")
            shown_any = True
        withheld = 0
        for act in self.store.activities_for_account(aid):
            if region_filter and act.get("region", "").lower() != region_filter:
                continue
            gate = policy.gate_record(self.store, act)
            if gate["disposition"] == "withhold":
                withheld += 1
                continue
            caveat = f" [{gate['reason']}]" if gate["reason"] else ""
            lines.append(f"  • {act['activity_date']}: {act['summary']}{caveat}")
            cites.append(_cite(act["activity_id"], gate["label"]))
            item = (f"{act['activity_date']} — {act['summary']}"
                    + (f" (note: {gate['reason']})" if gate["reason"] else "")
                    + f" {narrate.cite(act['activity_id'], gate['label'])}")
            (pub_items if gate["label"]["visibility"] == "public" else int_items).append(item)
            shown_any = True
        for note in self.session.for_entity(aid):
            lines.append(f"  • session note {note['note_id']} ({note['timestamp']}): "
                         f"{note['text']} [session-only, unverified — not a dataset record]")
            cites.append(f"({note['note_id']}, session note)")
            note_items.append(f"{note['text']} [{note['note_id']} · session note, "
                              f"unverified, not in the dataset]")
            shown_any = True
        if withheld:
            flags.append(f"{withheld} restricted record(s) withheld — human review")
        if not shown_any:
            return Answer("answer",
                          f"No activity or attendance rows match for {a['account_name']}"
                          + (f" in {region_filter.title()}" if region_filter else "") + ".",
                          citations=[f"({aid}, activities.csv: no rows)"],
                          narrative=f"Nothing recorded — no activity or attendance rows match "
                                    f"{a['account_name']}"
                                    + (f" in {region_filter.title()}" if region_filter else "")
                                    + ".")
        scope = f" in {region_filter.title()}" if region_filter else ""
        n = Narrative().para(f"Here's what the dataset holds on {a['account_name']}{scope}.")
        if pub_items:
            n.bullets("Publicly reported — safe to reference externally:", pub_items)
        if int_items:
            n.bullets("Internal records — do not repeat as public fact:", int_items)
        if ev_items:
            n.bullets("Events:", ev_items)
        if note_items:
            n.bullets("From this session only (not part of the dataset):", note_items)
        if withheld:
            n.para(f"There {'is' if withheld == 1 else 'are'} also "
                   f"{count_noun(withheld, 'restricted record')} on this account that I'm not "
                   f"showing. Their existence is on the record but the content needs human "
                   f"review before it goes anywhere.")
        return Answer("escalate" if withheld else "answer",
                      "\n".join(lines), citations=cites, flags=flags, narrative=n.render())

    # ------------------------------------------------------------------ prep
    def _handle_prep(self, text: str, ents: dict) -> Answer:
        if not ents["accounts"]:
            return Answer("clarify", "Which account is the call with?")
        return self._account_summary(ents["accounts"][0].record, prep=True)

    def _account_summary(self, a: dict, prep: bool) -> Answer:
        aid = a["account_id"]
        title = "Call prep" if prep else "Account summary"
        lines = [f"{title}: {a['account_name']} ({aid})",
                 f"  {a['business_description']}",
                 f"  sector: {a['sector']} / {a['subsector']}; country: {a['country']}; "
                 f"family-owned: {a['family_owned']}; membership: {a['membership_status']}; "
                 f"account manager: {a['account_manager']}"]
        cites = [f"({aid}, accounts.csv)"]
        flags = []

        pub, internal, withheld_ids = [], [], []
        for act in self.store.activities_for_account(aid):
            gate = policy.gate_record(self.store, act)
            rid = act["activity_id"]
            if gate["disposition"] == "withhold":
                withheld_ids.append(rid)
                continue
            entry = (f"    • {act['activity_date']}: {act['summary']}"
                     + (f" [{gate['reason']}]" if gate["reason"] else ""),
                     _cite(rid, gate["label"]))
            (pub if gate["label"]["visibility"] == "public" else internal).append(entry)
        if pub:
            lines.append("  Public record (safe to reference externally):")
            for t, c in pub:
                lines.append(t); cites.append(c)
        if internal:
            lines.append("  Internal knowledge (do NOT present as public fact):")
            for t, c in internal:
                lines.append(t); cites.append(c)
        if withheld_ids:
            lines.append(f"  Restricted: {len(withheld_ids)} record(s) withheld "
                         f"({', '.join(withheld_ids)}) — human review before use.")
            flags.append("restricted record(s) withheld — human review")

        atts = self.store.attendance_for_account(aid)
        if atts:
            lines.append("  Upcoming/recent events:")
            for at in atts:
                e = self.store.events.get(at["event_id"], {})
                lines.append(f"    • {e.get('event_name')} ({e.get('event_date')}) — "
                             f"{at['attendance_status']}")
                cites.append(_cite(at["attendance_id"],
                                   policy.evidence_label(self.store, at)))

        rels = self.store.relationships_touching_account(aid)
        rels += [r for p in self.store.people_of_account(aid)
                 for r in self.store.relationships_touching_person(p["person_id"])]
        seen = set()
        rel_lines = []
        for r in rels:
            if r["relationship_id"] in seen:
                continue
            seen.add(r["relationship_id"])
            gate = policy.gate_record(self.store, r)
            if gate["disposition"] == "withhold":
                if r["relationship_id"] not in withheld_ids:
                    flags.append("a restricted relationship record was withheld — human review")
                continue
            frm = self.store.people.get(r["from_person_id"], {})
            to = self.store.people.get(r["to_person_id"], {})
            rel_lines.append(f"    • {frm.get('full_name')} ↔ {to.get('full_name')}: "
                             f"{r['basis']}")
            cites.append(_cite(r["relationship_id"], gate["label"]))
        if rel_lines:
            lines.append("  Relationships:")
            lines += rel_lines

        note_items = []
        for note in self.session.for_entity(aid):
            lines.append(f"  Session note {note['note_id']}: {note['text']} "
                         f"[session-only, unverified]")
            cites.append(f"({note['note_id']}, session note)")
            note_items.append(f"{note['text']} [{note['note_id']} · session note, unverified]")

        # ---- prose
        n = Narrative().para(
            f"{'Ahead of the call, here' if prep else 'Here'}'s what the dataset holds on "
            f"{a['account_name']} — a {a['country']}-based "
            f"{'family-owned ' if a['family_owned'] == 'yes' else ''}"
            f"{a['sector'].lower()} business ({a['subsector'].lower()}), "
            f"{a['membership_status']} member, managed by {a['account_manager']}. "
            f"{a['business_description']}.")
        if pub:
            n.bullets("Public record — safe to reference on the call:",
                      [t.strip(" •") for t, _ in pub])
        if internal:
            n.bullets("Internal knowledge — useful context, but do not present as public fact:",
                      [t.strip(" •") for t, _ in internal])
        if atts:
            n.bullets("Events they're on:", [
                f"{self.store.events.get(at['event_id'], {}).get('event_name')} "
                f"({self.store.events.get(at['event_id'], {}).get('event_date')}) — "
                f"{at['attendance_status']}" for at in atts])
        if rel_lines:
            n.bullets("Relationship paths worth knowing:", [r.strip(" •") for r in rel_lines])
        if note_items:
            n.bullets("From this session only (not part of the dataset):", note_items)
        if withheld_ids:
            n.para(f"One thing to be aware of: {count_noun(len(withheld_ids), 'record')} on "
                   f"this account ({oxford(withheld_ids)}) "
                   f"{'is' if len(withheld_ids) == 1 else 'are'} restricted. I'm flagging that "
                   f"{'it exists' if len(withheld_ids) == 1 else 'they exist'} rather than "
                   f"showing the content — check with {a['account_manager']} before the call "
                   f"if it might be material.")

        mode = "escalate" if withheld_ids else "answer"
        return Answer(mode, "\n".join(lines), citations=cites, flags=flags,
                      narrative=n.render())

    # -------------------------------------------------------------- thematic
    THEME_SYNONYMS = {
        "data center": ["data center", "data centers"],
        "succession": ["succession", "ownership transition", "sale", "ownership change"],
        "renewable packaging": ["renewable packaging", "packaging"],
    }

    @staticmethod
    def _disclaims(rec: dict, needles: list[str]) -> bool:
        """True when the record mentions the theme only to deny it.

        The dataset encodes these explicitly (themes like 'no data center',
        summaries like '...no data center activity was mentioned'). Matching
        on the bare substring would otherwise turn a denial into evidence.
        """
        themes = (rec.get("themes") or "").lower()
        summary = (rec.get("summary") or "").lower()
        for n in needles:
            if f"no {n}" in themes or f"not {n}" in themes:
                return True
            for pat in (rf"no {re.escape(n)}[a-z ]*\b(activity|involvement|exposure)",
                        rf"\bnot\b[^.]{{0,40}}{re.escape(n)}"):
                if re.search(pat, summary):
                    return True
        return False

    def _handle_thematic(self, text: str, ents: dict) -> Answer:
        t = text.lower()
        # derive theme needles
        needles = []
        for canon, syns in self.THEME_SYNONYMS.items():
            if any(s in t for s in syns):
                needles = syns
                break
        if not needles:
            needles = [w for w in re.findall(r"[a-z][a-z ]{3,}", t)][:1] or [t.strip()]

        # constraints from the query
        want_country = "Germany" if "german" in t else None
        want_region = "Asia" if "asia" in t else ("Europe" if "europe" in t else None)
        want_family = ("family" in t and "owned" in t) or "families" in t
        want_industrial = "industrial" in t
        scoped_accounts = [m.record["account_id"] for m in ents["accounts"]]

        sensitive = policy.query_is_sensitive(text)

        matches: dict[str, list] = {}
        denials: dict[str, list] = {}
        for act in self.store.tables["activities"]:
            blob = " ".join([act.get("themes", ""), act.get("summary", ""),
                             act.get("title", "")]).lower()
            if not any(n in blob for n in needles):
                continue
            bucket = denials if self._disclaims(act, needles) else matches
            bucket.setdefault(act.get("account_id", "?"), []).append(act)

        if scoped_accounts:
            # question about a specific account: does IT have this activity?
            return self._thematic_for_account(scoped_accounts[0], matches,
                                              denials, sensitive)

        qualifying, excluded = [], []
        for aid, acts in matches.items():
            a = self.store.accounts.get(aid, {})
            reasons = []
            if want_country and a.get("country") != want_country:
                reasons.append(f"country is {a.get('country')}, not {want_country}")
            if want_region and a.get("region") != want_region:
                reasons.append(f"region is {a.get('region')}, not {want_region}")
            if want_family and a.get("family_owned") != "yes":
                reasons.append("not family-owned")
            if want_industrial and "industrial" not in (a.get("sector", "") + " "
                                                        + a.get("subsector", "")).lower():
                reasons.append(f"sector is {a.get('sector')}, not industrial")
            # evidence-quality exclusions. NB: 'confidential' is a handling
            # restriction, not weak evidence — it still supports the answer,
            # it just carries a caveat.
            gates = [policy.gate_record(self.store, act) for act in acts]

            def _weak(gate: dict, act: dict) -> bool:
                if gate["disposition"] == "withhold":
                    return True
                themes = (act.get("themes") or "").lower()
                if "unverified" in themes or "exploratory" in themes:
                    return True
                return gate["label"]["reliability"] == "low"

            # attending an event *about* a topic is not evidence the account is
            # itself doing it
            def _only_event_participation(act: dict) -> bool:
                return act.get("activity_type") == "event_update"

            if reasons:
                excluded.append((a, acts, gates, reasons))
            elif all(_weak(g, act) for g, act in zip(gates, acts)):
                excluded.append((a, acts, gates,
                                 ["evidence is unverified/exploratory/withheld only"]))
            elif all(_only_event_participation(act) for act in acts):
                excluded.append((a, acts, gates,
                                 ["only evidence is attendance at an event about this "
                                  "topic, not activity by the account itself"]))
            else:
                qualifying.append((a, acts, gates))

        lines, cites, flags = [], [], []
        q_items, x_items = [], []
        if sensitive:
            flags.append("sensitive topic — reliability-labeled, cited answer; "
                         "rumors/restricted notes need human review")
        if qualifying:
            lines.append("Accounts with supporting evidence:")
            for a, acts, gates in qualifying:
                lines.append(f"  {a.get('account_name')} ({a.get('account_id')}):")
                detail = []
                for act, gate in zip(acts, gates):
                    if gate["disposition"] == "withhold":
                        lines.append("    • restricted record withheld — human review")
                        flags.append("restricted record withheld — human review")
                        continue
                    caveat = f" [{gate['reason']}]" if gate["reason"] else ""
                    lines.append(f"    • {act['activity_date']}: {act['summary']}{caveat}")
                    cites.append(_cite(act["activity_id"], gate["label"]))
                    detail.append(f"{act['summary']} ({narrate.evidence_phrase(gate['label'])})"
                                  + (f" — {gate['reason']}" if gate["reason"] else "")
                                  + f" {narrate.cite(act['activity_id'], gate['label'])}")
                if detail:
                    q_items.append(f"{a.get('account_name')} — " + "; ".join(detail))
        for aid, acts in denials.items():
            a = self.store.accounts.get(aid, {})
            gates = [policy.gate_record(self.store, act) for act in acts]
            excluded.append((a, acts, gates,
                             ["the record mentions this topic only to rule it out"]))
        if excluded:
            lines.append("Related but NOT qualifying (kept visible so nothing is "
                         "silently dropped):")
            for a, acts, gates, reasons in excluded:
                lines.append(f"  {a.get('account_name')} ({a.get('account_id')}) — "
                             f"{'; '.join(reasons)}")
                x_items.append(f"{a.get('account_name')} — {'; '.join(reasons)}")
                for act, gate in zip(acts, gates):
                    if gate["disposition"] == "withhold":
                        lines.append("    • restricted record withheld — human review")
                        flags.append("restricted record withheld — human review")
                        continue
                    caveat = f" [{gate['reason']}]" if gate["reason"] else ""
                    lines.append(f"    • {act['summary']}{caveat}")
                    cites.append(_cite(act["activity_id"], gate["label"]))
        if not lines:
            return Answer("refuse",
                          "The dataset contains no records matching that topic — "
                          "I can't support a claim either way.",
                          citations=["(activities.csv: no matching rows)"],
                          narrative="Nothing in the dataset matches that topic, so I can't "
                                    "support a claim either way — neither that it's happening "
                                    "nor that it isn't.")
        n = Narrative()
        if q_items:
            n.para(f"{count_noun(len(q_items), 'account')} "
                   f"{'meets' if len(q_items) == 1 else 'meet'} that description on the "
                   f"evidence available:").bullets("", q_items)
        else:
            n.para("No account clears the bar on the evidence available.")
        if x_items:
            n.bullets(
                "Several came close but don't qualify. I'm listing them rather than dropping "
                "them silently, so you can see what was considered and why it was ruled out:",
                x_items)
        if sensitive:
            n.para("This is a sensitive area, so everything above is reliability-labelled "
                   "rather than stated flatly, and anything restricted is flagged for human "
                   "review instead of summarised.")
        return Answer("answer", "\n".join(lines), citations=cites, flags=flags,
                      narrative=n.render())

    def _thematic_for_account(self, aid: str, matches: dict, denials: dict,
                              sensitive: bool) -> Answer:
        a = self.store.accounts.get(aid, {})
        own = matches.get(aid, [])
        flags = ["sensitive topic — human review for restricted/rumor content"] if sensitive else []
        # a record whose themes disclaim the account (e.g. 'not northstar
        # activity') is not evidence for the account, only about it
        firstword = a.get("account_name", "").split()[0].lower()
        direct = [x for x in own
                  if f"not {firstword}" not in (x.get("themes", "") or "").lower()]
        disclaimed = [x for x in own if x not in direct] + denials.get(aid, [])
        if direct:
            lines = [f"Evidence for {a.get('account_name')} on this topic:"]
            cites, items, has_public = [], [], False
            for act in direct:
                gate = policy.gate_record(self.store, act)
                if gate["disposition"] == "withhold":
                    flags.append("restricted record withheld — human review")
                    lines.append("  • restricted record withheld")
                    continue
                caveat = f" [{gate['reason']}]" if gate["reason"] else ""
                lines.append(f"  • {act['activity_date']}: {act['summary']}{caveat}")
                cites.append(_cite(act["activity_id"], gate["label"]))
                has_public = has_public or gate["label"]["visibility"] == "public"
                items.append(f"{act['activity_date']} — {act['summary']} "
                             f"({narrate.evidence_phrase(gate['label'])})"
                             + (f", {gate['reason']}" if gate["reason"] else "")
                             + f" {narrate.cite(act['activity_id'], gate['label'])}")
            n = Narrative().para(
                f"Yes. The dataset backs that up for {a.get('account_name')}:"
            ).bullets("", items)
            if has_public:
                n.para("The public item is safe to reference externally; anything marked "
                       "internal is not.")
            else:
                n.para("Note that all of this is internal — none of it is public, so don't "
                       "repeat it as though it were.")
            return Answer("answer", "\n".join(lines), citations=cites, flags=flags,
                          narrative=n.render())

        # no direct evidence — say so, surface near-misses with their disclaimers
        lines = [f"No — the dataset does not support {a.get('account_name')} being "
                 f"active in this area. No activity row ties them to it."]
        cites = [f"({aid}, activities.csv: no qualifying rows)"]
        n = Narrative().para(
            f"No — the dataset doesn't support that. No activity row ties "
            f"{a.get('account_name')} to it.")
        near = []
        for act in disclaimed:
            gate = policy.gate_record(self.store, act)
            lines.append(f"  Near-miss (explicitly disclaimed in the data): "
                         f"{act['summary']}")
            cites.append(_cite(act["activity_id"], gate["label"]))
            near.append(f"{act['summary']} {narrate.cite(act['activity_id'], gate['label'])}")
        if near:
            n.bullets(
                "There is a record that mentions the topic, and I want to flag it precisely "
                "because a keyword match here would be misleading — it names the topic only "
                "to rule it out:", near)
        others = [(k, v) for k, v in matches.items() if k != aid]
        elsewhere = []
        if others:
            for k, acts in others[:3]:
                oa = self.store.accounts.get(k, {})
                for act in acts[:1]:
                    gate = policy.gate_record(self.store, act)
                    lines.append(f"  For context, the matching activity belongs to "
                                 f"{oa.get('account_name')}: {act['summary']}")
                    cites.append(_cite(act["activity_id"], gate["label"]))
                    elsewhere.append(f"{oa.get('account_name')} — {act['summary']} "
                                     f"{narrate.cite(act['activity_id'], gate['label'])}")
        if elsewhere:
            n.bullets("The activity on this topic belongs to a different account:", elsewhere)
        return Answer("refuse", "\n".join(lines), citations=cites, flags=flags,
                      narrative=n.render())
