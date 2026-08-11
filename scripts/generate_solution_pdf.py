from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
OUT_PATH = OUT_DIR / "owners_forum_case_study_solution.pdf"


SECTIONS = [
    (
        "1. Architecture note",
        [
            "Structured retrieval over the 7 CSVs: resolve entities, join rows, apply policy, then compose a cited answer.",
            "Deliberately not vector RAG: the dataset is small and ID driven, so deterministic joins are simpler and more exact.",
            "The LLM layer is optional and post gate only. It rewrites style, but does not retrieve or decide policy.",
            "policy.py is the single rules file for contact visibility, sensitivity, staleness, and evidence labels.",
        ],
    ),
    (
        "2. Context and memory note",
        [
            "Context is session scoped and in process only: last resolved entities plus an in memory note store.",
            "Pronoun carry over happens only when the new turn resolves nothing and the wording clearly refers back.",
            "Clarify follow ups resume the original question when the user answers with a record id or short disambiguator.",
            "Notes that match no dataset entity stay unlinked rather than being attached by guesswork.",
        ],
    ),
    (
        "3. Retrieval strategy note",
        [
            "All CSVs are loaded into memory with primary key indexes and explicit join helpers, so retrieval paths stay readable and testable.",
            "Entity resolution is tiered: record ids first, then exact names, then limited partial name fallbacks.",
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
            "When possible, a note links to resolved entity ids. Otherwise it is stored unlinked.",
        ],
    ),
    (
        "5. Decision logic note",
        [
            "answer: enough grounded evidence, no unresolved ambiguity, citations attached to each claim.",
            "clarify: multiple matching people, accounts, or events, so the assistant shows options and waits.",
            "refuse: restricted contact detail or unsupported claim. It states why rather than going quiet.",
            "escalate: sensitive or restricted material is in scope, so content is withheld and human review is flagged.",
            "Cross cutting rule: stale, low reliability, unverified, or explicitly denied evidence is shown with caveats instead of being silently dropped.",
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
            "policy.py keeps the rule layer explicit, so privacy and sensitivity handling stays readable in code.",
            "This is a trusted internal prototype, not a multi tenant system. Real deployment would need caller auth and role aware policy.",
            "Intent detection is still keyword based, so unusual phrasing should eventually move to a classifier with confidence thresholds.",
        ],
    ),
]


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="DeckTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=30,
            textColor=colors.HexColor("#1a150d"),
            alignment=TA_LEFT,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DeckSub",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#61553f"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#1a150d"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodySmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor("#2d261c"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="BulletSmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor("#2d261c"),
            leftIndent=10,
            firstLineIndent=-8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="StatLabel",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#7a6b51"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="StatValue",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=22,
            textColor=colors.HexColor("#c5961e"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="StatDesc",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.5,
            textColor=colors.HexColor("#61553f"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="CalloutTitle",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#1a150d"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Footer",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#7a6b51"),
            alignment=TA_LEFT,
        )
    )
    return styles


def stat_cell(label: str, value: str, desc: str, styles):
    return [
        Paragraph(label, styles["StatLabel"]),
        Spacer(1, 3),
        Paragraph(value, styles["StatValue"]),
        Spacer(1, 2),
        Paragraph(desc, styles["StatDesc"]),
    ]


def make_stat_table(styles):
    table = Table(
        [[
            stat_cell("Eval", "52/52", "checks passing", styles),
            stat_cell("Prompts", "15", "fixed regression set", styles),
            stat_cell("Surfaces", "3", "web, CLI, eval", styles),
        ]],
        colWidths=[57 * mm, 57 * mm, 57 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f1e7")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d6c6a7")),
                ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#e4d7bf")),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def make_callout(title: str, body_lines: list[str], styles, width: float):
    body = [Paragraph(title, styles["CalloutTitle"])]
    for line in body_lines:
        body.append(Paragraph(line, styles["BodySmall"]))
        body.append(Spacer(1, 2))
    table = Table([[body]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbf7ef")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d6c6a7")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return table


def make_section_card(title: str, bullets: list[str], styles, width: float):
    flowables = [Paragraph(title, styles["SectionTitle"])]
    for bullet in bullets:
        flowables.append(Paragraph(f"• {bullet}", styles["BulletSmall"]))
    table = Table([[flowables]], colWidths=[width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbf7ef")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d6c6a7")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return KeepTogether([table, Spacer(1, 10)])


def draw_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#7a6b51"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(doc.leftMargin, 10 * mm, "Owners Forum Case Study Solution")
    canvas.drawRightString(A4[0] - doc.rightMargin, 10 * mm, str(doc.page))
    canvas.restoreState()


def build_pdf():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="Owners Forum Case Study Solution",
        author="OpenAI Codex",
    )

    width = A4[0] - doc.leftMargin - doc.rightMargin
    story = [
        Paragraph("Owners Forum Case Study Solution", styles["DeckTitle"]),
        Paragraph(
            "Runnable prototype summary plus the seven requested deliverable notes.",
            styles["DeckSub"],
        ),
        Spacer(1, 8),
        make_stat_table(styles),
        Spacer(1, 14),
        make_callout(
            "Prototype summary",
            [
                "Deterministic grounded assistant over a closed 7 CSV dataset.",
                "No API key required for the core prototype.",
                "Web app, CLI, and regression evaluation are included in the submission bundle.",
            ],
            styles,
            width,
        ),
        Spacer(1, 10),
        make_callout(
            "Why this design",
            [
                "The dataset is small, structured, and closed, so deterministic retrieval is easier to audit and defend.",
                "Exact citations and privacy rules are enforced in code rather than delegated to a model.",
                "If the graph and data grow, a model becomes useful for query planning, fuzzy mapping, and summarizing larger evidence sets.",
            ],
            styles,
            width,
        ),
        Spacer(1, 10),
        make_callout(
            "Run locally",
            [
                "Web app: <font name='Courier'>python3 -m solution.web.server</font>",
                "CLI: <font name='Courier'>python3 -m solution.assistant.cli</font>",
                "Eval: <font name='Courier'>python3 solution/eval/run_eval.py</font>",
                "Data is loaded from the <font name='Courier'>data/</font> folder by default.",
            ],
            styles,
            width,
        ),
        Spacer(1, 10),
        Preformatted(
            "Submission contents\n"
            "README.md\n"
            "EXPLANATION.md\n"
            "solution/NOTES.md\n"
            "solution/\n"
            "data/\n",
            ParagraphStyle(
                "MonoBox",
                parent=styles["BodySmall"],
                fontName="Courier",
                fontSize=8.5,
                leading=12,
                backColor=colors.HexColor("#f3ead5"),
                borderColor=colors.HexColor("#d6c6a7"),
                borderWidth=0.6,
                borderPadding=10,
            ),
        ),
        PageBreak(),
    ]

    for title, bullets in SECTIONS:
        story.append(make_section_card(title, bullets, styles, width))

    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Source of record: solution/NOTES.md. This PDF is a packaged version of the deliverable notes.",
            styles["Footer"],
        )
    )

    doc.build(story, onFirstPage=draw_page_number, onLaterPages=draw_page_number)


if __name__ == "__main__":
    build_pdf()
