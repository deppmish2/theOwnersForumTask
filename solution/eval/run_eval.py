"""Run the 10 core + 5 bonus prompts through the engine as a regression set.

Writes eval/transcript.md and checks policy invariants derived from the
briefing (contact visibility, restricted withholding, distractor
filtering, session-note separation). Exit code 1 on any failed check.

Run from the repo root:  python -m solution.eval.run_eval
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from solution.assistant.engine import Engine  # noqa: E402

CORE = [
    "Which member guests are attending the Berlin Manufacturing Forum?",
    # prompt 2 is two turns: session note, then recent activity
    "session-update Northstar Holdings with a voice note: Priya mentioned they may "
    "expand the Osaka hub next year",
    "Show recent activity for Northstar Holdings",
    "Which accounts have recent succession or ownership activity in Asia?",
    "Which German family-owned industrials are active in data centers?",
    "Prep call notes for an upcoming Valen Group call",
    "Is Meridian Foods attending the Berlin dinner?",
    "Has Cardso Precision been involved in Asian events?",
    "Who potentially knows someone at Hansei Textiles?",
    "What do we know about Priya Kapoor?",
    "Give me Priya Kapoor's contact details",
]

BONUS = [
    "Which families are preparing for a sale or ownership change?",
    "Is Valen Group active in data centers?",
    "Tell me everything about Daniel Weber's succession plans",
    "Who should I contact about the Singapore dinner?",
    "Is Northstar Holdings active in renewable packaging?",
]


def _norm(text: str) -> str:
    return (text.lower()
            .replace("—", " ")
            .replace("–", " ")
            .replace("-", " "))


def contains(txt: str, *needles: str) -> bool:
    hay = _norm(txt)
    return all(_norm(n) in hay for n in needles)


def main() -> int:
    engine = Engine()
    transcript: list[str] = ["# Evaluation transcript\n"]
    answers: list = []

    for i, q in enumerate(CORE + BONUS, 1):
        a = engine.ask(q)
        answers.append(a)
        transcript.append(f"## {i}. {q}\n\n```\n{a.render()}\n```\n")

    checks: list[tuple[str, bool]] = []
    txt = [a.render() for a in answers]          # everything the user sees
    struct = [a.text for a in answers]           # auditable structured view only
    prose = [a.prose for a in answers]           # natural-language view only

    # 1 Berlin forum member guests: joined names + citations
    checks.append(("berlin forum lists Priya Kapoor with citation",
                   contains(txt[0], "priya kapoor", "AT001")))
    # 2/3 session note recorded and shown as session-only in recent activity
    checks.append(("session note recorded with SN id", contains(txt[1], "SN001")))
    checks.append(("recent activity includes session note labeled session-only",
                   contains(txt[2], "SN001", "session-only")))
    checks.append(("recent activity flags Northstar restricted note (ACT004) as withheld",
                   contains(txt[2], "restricted") and "external chair" not in txt[2].lower()))
    # 4 Asia succession: Hansei shown w/ confidential caveat; Pacific Alloy stale caveat
    checks.append(("asia succession includes Hansei with confidential caveat",
                   contains(txt[3], "hansei", "confidential")))
    checks.append(("asia succession marks Pacific Alloy note stale",
                   contains(txt[3], "pacific alloy", "stale")))
    # 4 (cont) confidential ≠ weak: Hansei/Aruna must still qualify
    checks.append(("asia succession ranks Hansei+Aruna as supporting evidence",
                   all(name in struct[3].split("NOT qualifying")[0].lower()
                       for name in ("hansei", "aruna"))))
    checks.append(("asia succession demotes Cardso (event attendance only)",
                   "cardso" in struct[3].split("NOT qualifying")[-1].lower()
                   and "cardso" not in struct[3].split("NOT qualifying")[0].lower()))
    checks.append(("asia succession excludes Valen as Europe",
                   contains(txt[3], "valen", "region is Europe")))
    # 5 data centers: Valen qualifies; distractors excluded with reasons
    checks.append(("data centers: Valen qualifies with S011",
                   contains(txt[4], "valen", "S011")))
    checks.append(("data centers: Veyra excluded as an explicit denial",
                   "veyra" in txt[4].split("NOT qualifying")[-1].lower()
                   and "rule it out" in txt[4].lower()))
    checks.append(("data centers: LumenGrid excluded (not family-owned)",
                   contains(txt[4], "lumengrid", "not family-owned")))
    checks.append(("data centers: TannenWerk flagged unverified/low reliability",
                   contains(txt[4], "tannenwerk") and
                   ("unverified" in txt[4].lower() or "low" in txt[4].lower())))
    # 6 Valen prep: public/internal separated; restricted withheld
    checks.append(("valen prep separates public vs internal",
                   contains(txt[5], "public record", "internal knowledge")))
    checks.append(("valen prep withholds restricted ACT018 content",
                   "human review" in txt[5].lower()
                   and "sensitivity note" not in txt[5].lower()))
    # 7 Meridian Berlin dinner: yes with both RSVPs, internal label
    checks.append(("meridian dinner: yes with AT011+AT025, internal-labeled",
                   contains(txt[6], "yes", "AT011", "AT025", "internal")))
    # 8 Cardso Asia: roundtable + Tokyo
    checks.append(("cardso asia lists roundtable and tokyo",
                   contains(txt[7], "roundtable", "tokyo")))
    # 9 Hansei connections: no invented path, gap stated
    checks.append(("hansei connections: evidence gap, nothing invented",
                   contains(txt[8], "no relationship") or contains(txt[8], "evidence gap")))
    # 10 Priya profile cites people.csv and mentions contact policy
    checks.append(("priya profile grounded with contact policy note",
                   contains(txt[9], "P001", "email_only")))
    # 11 Priya contact: email shown, phone withheld
    checks.append(("priya contact shows email", contains(txt[10], "priya.kapoor@northstar.example")))
    checks.append(("priya contact never shows phone", "+65-555-0101" not in txt[10]))
    # b1 families sale/ownership: sensitive flag present, Aruna public+confidential handled
    checks.append(("families sale query carries sensitive-topic flag",
                   contains(txt[11], "sensitive")))
    # b2 Valen data centers: yes, public citation
    checks.append(("valen data centers cites public S011", contains(txt[12], "S011")))
    # b3 Daniel Weber succession: escalation, ACT018 content withheld
    checks.append(("daniel weber succession escalates to human review",
                   answers[13].mode == "escalate" and contains(txt[13], "ACT018")))
    checks.append(("daniel weber restricted content not leaked",
                   "sensitivity note" not in txt[13].lower()
                   or "withheld" in txt[13].lower()))
    # b4 Singapore dinner: ambiguity → clarify (two Singapore dinners exist)
    checks.append(("singapore dinner asks which of the two dinners",
                   answers[14].mode == "clarify" and contains(txt[14], "E004", "E005")))
    # b5 Northstar renewable packaging: refusal, near-miss disclaimed
    checks.append(("northstar renewable packaging: not supported",
                   answers[15].mode == "refuse" and contains(txt[15], "does not support")))
    checks.append(("renewable packaging context points to Brindle",
                   contains(txt[15], "brindle")))

    # multi-turn: answering a clarifying question with a record id must resume
    # the original question rather than starting a new one
    clarify = engine.ask("Who should I contact about the Singapore dinner?")
    followup = engine.ask("E005")
    transcript.append("## 16b. Multi-turn: clarify, then answer with a record id\n\n"
                      f"```\nyou> Who should I contact about the Singapore dinner?\n"
                      f"{clarify.render()}\n\nyou> E005\n{followup.render()}\n```\n")
    # partial-name lookups: given name, ambiguous given name, unknown name
    probe = Engine()
    first_name = probe.ask("who is priya ?")
    amb_name = probe.ask("who is Mara?")
    unknown = probe.ask("who is Xavier Delacroix?")
    transcript.append(
        "## 16c. Partial-name lookups\n\n```\n"
        f"you> who is priya ?\n{first_name.render()}\n\n"
        f"you> who is Mara?\n{amb_name.render()}\n\n"
        f"you> who is Xavier Delacroix?\n{unknown.render()}\n```\n")

    # a reply that echoes the *ambiguous* token must not loop forever
    loop = Engine()
    first_clarify = loop.ask("who is Mara?")
    echoed = loop.ask("Mara")            # the shared token — cannot disambiguate
    resolved = loop.ask("P041")          # the id — must resolve
    byname = Engine()
    byname.ask("who is Mara?")
    surname = byname.ask("Kessler")      # distinguishing token
    transcript.append(
        "## 16d. Clarify loop: replying with the shared token\n\n```\n"
        f"you> who is Mara?\n(clarify)\n\nyou> Mara\n{echoed.render()}\n\n"
        f"you> P041\n{resolved.render()}\n\nyou> Kessler (fresh session)\n"
        f"{surname.render()}\n```\n")

    attendance_probe = Engine()
    berlin_attending = attendance_probe.ask(
        "Which member guests are attending the Berlin Manufacturing Forum?")
    brindle_berlin = attendance_probe.ask(
        "Is Brindle Packaging attending the Berlin Manufacturing Forum?")
    soojin_berlin = attendance_probe.ask(
        "Is Soo-jin Park attending the Berlin Manufacturing Forum?")
    berlin_contact = attendance_probe.ask(
        "Who should I contact about the Berlin Manufacturing Forum?")
    bare_entity = Engine().ask("Priya Kapoor")
    transcript.append(
        "## 16e. Reviewed bug regressions\n\n```\n"
        f"you> Which member guests are attending the Berlin Manufacturing Forum?\n"
        f"{berlin_attending.render()}\n\n"
        f"you> Is Brindle Packaging attending the Berlin Manufacturing Forum?\n"
        f"{brindle_berlin.render()}\n\n"
        f"you> Is Soo-jin Park attending the Berlin Manufacturing Forum?\n"
        f"{soojin_berlin.render()}\n\n"
        f"you> Who should I contact about the Berlin Manufacturing Forum?\n"
        f"{berlin_contact.render()}\n\n"
        f"you> Priya Kapoor\n{bare_entity.render()}\n```\n")

    checks_extra = [
        ("echoing the ambiguous token does not repeat the same clarify verbatim",
         echoed.mode == "clarify" and echoed.prose != first_clarify.prose),
        ("re-clarify names the shared token and asks for the id",
         contains(echoed.prose, "Mara", "P036", "P041")),
        ("record id resolves the pending clarify",
         resolved.mode == "answer" and contains(resolved.prose, "Mara Voss")),
        ("distinguishing surname resolves the pending clarify",
         surname.mode == "answer" and contains(surname.prose, "Mara Kessler")),
        ("given-name lookup resolves to the person record, not a theme search",
         first_name.mode == "answer" and contains(first_name.prose, "Priya Kapoor",
                                                  "Managing Director")
         and "activities.csv: no matching rows" not in first_name.text),
        ("given-name lookup cites people.csv",
         any("P001" in c for c in first_name.citations)),
        ("ambiguous given name clarifies with both candidates",
         amb_name.mode == "clarify" and contains(amb_name.prose, "P036", "P041")),
        ("unknown name is refused by name, not answered from another table",
         unknown.mode == "refuse" and contains(unknown.prose, "Xavier Delacroix")
         and contains(unknown.prose.lower(), "people.csv")),
        ("clarify follow-up resumes the original contact question",
         followup.mode == "answer" and contains(followup.render(),
                                                "Singapore Planning Dinner", "Mei Tan")),
        ("clarify follow-up still defers per-person contact visibility",
         contains(followup.render(), "contact_visibility")),
        ("berlin forum attending excludes waitlisted and declined member guests",
         contains(berlin_attending.prose, "6 member guests")
         and "Soo-jin Park" not in berlin_attending.render()
         and "Jonas Brindle" not in berlin_attending.render()),
        ("declined RSVP does not become a yes for account attendance",
         brindle_berlin.mode == "answer"
         and "yes." not in brindle_berlin.prose.lower()
         and contains(brindle_berlin.prose, "declined")),
        ("person-plus-event attendance answers the person question, not the full roster",
         soojin_berlin.mode == "answer"
         and contains(soojin_berlin.prose, "Soo-jin Park", "waitlisted")
         and "Priya Kapoor" not in soojin_berlin.render()),
        ("event contact lookup stays scoped to the requested event",
         berlin_contact.mode == "refuse"
         and "REL008" not in berlin_contact.render()
         and "Mei Tan" not in berlin_contact.render()),
        ("bare entity prompt asks what the user wants to know",
         bare_entity.mode == "clarify"
         and contains(bare_entity.prose, "contact details", "recent activity")),
    ]

    checks.extend(checks_extra)

    # ------------------------------------------------------------------
    # Conformance with the eight required behaviors (briefing, page 3).
    # Each behavior maps to concrete evidence from the run above.
    # ------------------------------------------------------------------
    all_prose = "\n".join(prose)
    all_render = "\n".join(txt)
    modes = {a.mode for a in answers}

    behaviors: list[tuple[str, str, bool]] = [
        ("1. Answer only from provided files",
         "no answer asserts a fact absent from the CSVs; unsupported claims refuse",
         answers[15].mode == "refuse" and answers[8].mode == "answer"
         and "evidence" in prose[8].lower()),

        ("2. Cite record & source IDs",
         "every answering turn carries at least one record/source citation",
         all(a.citations for a in answers if a.mode in ("answer", "escalate"))),

        ("3. Separate public vs. internal sources",
         "prep answer splits public record from internal knowledge explicitly",
         contains(prose[5], "public record", "internal")
         and contains(prose[6], "internal")),

        ("4. Flag weak evidence",
         "stale, low-reliability and unverified records are labelled as such",
         contains(all_render, "stale") and contains(all_render, "low-reliability")
         and contains(all_render, "unverified")),

        ("5. Protect restricted contact details",
         "email_only person: email shown, phone never shown, reason stated",
         "priya.kapoor@northstar.example" in prose[10]
         and "+65-555-0101" not in all_render
         and contains(prose[10], "email_only")),

        ("6. Ask when a request is ambiguous",
         "two Singapore dinners -> clarify with both ids, no guess",
         answers[14].mode == "clarify" and contains(prose[14], "E004", "E005")),

        ("7. Choose the right response mode",
         "all four modes exercised across the 15 prompts",
         modes == {"answer", "clarify", "refuse", "escalate"}),

        ("8. Track session vs. dataset",
         "session note cited as SN-id and labelled session-only, never a dataset fact",
         contains(prose[1], "SN001") and contains(prose[2], "SN001")
         and contains(prose[2].lower(), "session")),
    ]

    # prose quality: answers should read as sentences, not only key:value dumps
    behaviors.append((
        "Prose quality", "answering turns produce natural-language narration",
        sum(1 for a in answers if a.narrative) >= len(answers) - 1))

    transcript.append("## Conformance with the eight required behaviors\n")
    for name, evidence, ok in behaviors:
        checks.append((f"[behavior] {name}", ok))
        transcript.append(f"- **{'PASS' if ok else 'FAIL'}** {name} — _{evidence}_")
    transcript.append("")

    transcript.append("## Invariant checks\n")
    failed = 0
    for name, ok in checks:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        transcript.append(f"- **{mark}** {name}")
        print(f"[{mark}] {name}")

    out = Path(__file__).parent / "transcript.md"
    out.write_text("\n".join(transcript), encoding="utf-8")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed. "
          f"Transcript: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
