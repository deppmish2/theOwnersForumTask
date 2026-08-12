from __future__ import annotations

from pathlib import Path
import re
import shutil

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
OUT_PATH = OUT_DIR / "owners_forum_case_study_solution.pdf"
ROOT_OUT_DIR = ROOT / "output"
ROOT_OUT_PATH = ROOT_OUT_DIR / "owners_forum_case_study_solution.pdf"


SECTIONS = [
    (
        "1. Architecture note",
        [
            "Structured retrieval over the 7 CSVs: resolve entities, join rows, apply policy, then compose a cited answer.",
            "The dataset is small and ID driven, so deterministic joins are simpler and more exact than vector retrieval here.",
            "The LLM layer is optional and post gate only. It rewrites style, but does not retrieve or decide policy.",
            "policy.py implements the provided policies.md, and data.py validates the CSV schema against data_dictionary.md.",
        ],
    ),
    (
        "2. Context and memory note",
        [
            "Context is session scoped and in process only: last resolved entities plus an in memory note store.",
            "Pronoun carry over happens only when the new turn resolves nothing and the wording clearly refers back.",
            "Clarify follow ups resume the original question when the user answers with a record ID or short disambiguator.",
            "Notes that match no dataset entity stay unlinked rather than being attached by guesswork.",
        ],
    ),
    (
        "3. Retrieval strategy note",
        [
            "All CSVs are loaded into memory with primary key indexes and explicit join helpers, so retrieval paths stay readable and testable.",
            "Entity resolution is tiered: record IDs first, then exact names, then limited partial name fallbacks.",
            "Ambiguity is a first class result. The assistant returns options and asks instead of picking one.",
            "Thematic questions use structured filters, negation checks, and evidence quality checks rather than semantic similarity.",
        ],
    ),
    (
        "4. Session notes note",
        [
            "Session notes live in a separate append only store and are never written back into the CSVs.",
            "They use a separate citation namespace such as SN001 and always render as session only, unverified material.",
            "Notes are surfaced alongside dataset facts, not merged into them.",
            "When possible, a note links to resolved entity IDs. Otherwise it is stored unlinked.",
        ],
    ),
    (
        "5. Decision logic note",
        [
            "answer: enough grounded evidence, no unresolved ambiguity, citations attached to each claim.",
            "clarify: multiple matching people, accounts, or events, so the assistant shows options and waits.",
            "refuse: restricted contact detail or unsupported claim. It states why rather than going quiet.",
            "escalate: sensitive or restricted material is in scope, so content is withheld and human review is flagged.",
            "Stale, low reliability, unverified, or explicitly denied evidence is shown with caveats instead of being silently dropped.",
        ],
    ),
    (
        "6. Evaluation plan",
        [
            "The 15 provided prompts are the fixed regression set, and every run writes a transcript for review.",
            "52 automated checks cover privacy, citation behavior, ambiguity, thematic filtering, and RSVP and contact edge cases.",
            "The suite is aimed at judgment failures, not just crashes. Wrong but plausible answers are the main target.",
            "With more time I would add per claim citation audits, prompt injection tests, and a small human rated usefulness pass.",
        ],
    ),
    (
        "7. Privacy and limitations note",
        [
            "Contact visibility is enforced in code before composition, so restricted details never depend on prompt compliance.",
            "Restricted records are filtered before the optional LLM layer, so withheld content never enters model context.",
            "The provided policies.md and data_dictionary.md are reflected directly in policy.py and data.py.",
            "This is a trusted internal prototype, not a multi tenant system. Real deployment would need caller auth and role aware policy.",
            "Intent detection is still keyword based, so unusual phrasing should eventually move to a classifier with confidence thresholds.",
        ],
    ),
]


def plain(text: str) -> str:
    text = re.sub(r"[-–—]+", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def format_item(text: str) -> str:
    cleaned = plain(text)
    for label in ("answer:", "clarify:", "refuse:", "escalate:"):
        if cleaned.lower().startswith(label):
            rest = cleaned[len(label):].lstrip()
            return f"<b>{label}</b> {rest}"
    return cleaned


def build_styles():
    base = getSampleStyleSheet()
    base.add(
        ParagraphStyle(
            name="SimpleTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.black,
            spaceAfter=10,
        )
    )
    base.add(
        ParagraphStyle(
            name="SimpleBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=colors.black,
            spaceAfter=10,
        )
    )
    base.add(
        ParagraphStyle(
            name="SimpleHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.black,
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    base.add(
        ParagraphStyle(
            name="SimpleItem",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=colors.black,
            leftIndent=10,
            rightIndent=4,
            spaceAfter=6,
        )
    )
    base.add(
        ParagraphStyle(
            name="RunLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=colors.black,
        )
    )
    base.add(
        ParagraphStyle(
            name="RunCode",
            parent=base["BodyText"],
            fontName="Courier",
            fontSize=10,
            leading=14,
            textColor=colors.black,
        )
    )
    base.add(
        ParagraphStyle(
            name="SimpleFooter",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.black,
        )
    )
    return base


def make_run_table(styles):
    rows = [
        [
            Paragraph("Web app", styles["RunLabel"]),
            Paragraph("python3 -m solution.web.server", styles["RunCode"]),
        ],
        [
            Paragraph("CLI", styles["RunLabel"]),
            Paragraph("python3 -m solution.assistant.cli", styles["RunCode"]),
        ],
        [
            Paragraph("Eval", styles["RunLabel"]),
            Paragraph("python3 -m solution.eval.run_eval", styles["RunCode"]),
        ],
    ]
    table = Table(rows, colWidths=[28 * mm, 110 * mm])
    table.setStyle(
        TableStyle(
            [
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.black)
    canvas.drawString(doc.leftMargin, 10 * mm, plain("Owners Forum Case Study Solution"))
    canvas.drawRightString(A4[0] - doc.rightMargin, 10 * mm, str(doc.page))
    canvas.restoreState()


def build_story(styles):
    story = [
        Paragraph(plain("Owners Forum Case Study Solution"), styles["SimpleTitle"]),
        Paragraph(
            plain("Simple submission summary and the seven requested deliverable notes."),
            styles["SimpleBody"],
        ),
        Paragraph(
            plain("Summary: deterministic grounded assistant over 7 CSVs, optional post gate LLM rewrite layer, web app plus CLI, and 52 of 52 evaluation checks passing."),
            styles["SimpleBody"],
        ),
        Paragraph(plain("Run locally:"), styles["SimpleHeading"]),
        make_run_table(styles),
        Spacer(1, 10),
    ]

    for title, bullets in SECTIONS:
        story.append(Paragraph(plain(title), styles["SimpleHeading"]))
        for bullet in bullets:
            story.append(Paragraph(format_item(bullet), styles["SimpleItem"]))
        story.append(Spacer(1, 3))

    story.append(
        Paragraph(
            plain("Source of record: solution/NOTES.md. This PDF is a plain text packaged version of the deliverable notes."),
            styles["SimpleFooter"],
        )
    )
    return story


def build_pdf():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ROOT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="Owners Forum Case Study Solution",
        author="OpenAI Codex",
    )
    doc.build(build_story(styles), onFirstPage=draw_footer, onLaterPages=draw_footer)
    shutil.copy2(OUT_PATH, ROOT_OUT_PATH)


if __name__ == "__main__":
    build_pdf()
