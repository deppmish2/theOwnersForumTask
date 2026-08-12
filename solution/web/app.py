"""Shared web app logic for local and Vercel serving."""

from __future__ import annotations

from pathlib import Path
import secrets

from solution.assistant.engine import Engine
from solution.assistant.data import Store
from solution.assistant import llm
from solution.assistant.narrate import natural_text


# Share the root page between local serving and Vercel request routing.
STATIC = Path(__file__).resolve().parents[2] / "index.html"

# one Store shared by every session (read only); one Engine per browser session
_STORE = Store()
_SESSIONS: dict[str, Engine] = {}

EXAMPLES = {
    "Core prompts": [
        "Which member guests are attending the Berlin Manufacturing Forum?",
        "note: Priya mentioned they may expand the Osaka hub next year",
        "Show recent activity for Northstar Holdings",
        "Which accounts have recent succession or ownership activity in Asia?",
        "Which German family-owned industrials are active in data centers?",
        "Prep call notes for an upcoming Valen Group call",
        "Is Meridian Foods attending the Berlin dinner?",
        "Has Cardso Precision been involved in Asian events?",
        "Who potentially knows someone at Hansei Textiles?",
        "What do we know about Priya Kapoor?",
        "Give me Priya Kapoor's contact details",
    ],
    "Bonus prompts": [
        "Which families are preparing for a sale or ownership change?",
        "Is Valen Group active in data centers?",
        "Tell me everything about Daniel Weber's succession plans",
        "Who should I contact about the Singapore dinner?",
        "Is Northstar Holdings active in renewable packaging?",
    ],
}


def index_html_bytes() -> bytes:
    return STATIC.read_bytes()


def _engine_for(sid: str) -> Engine:
    if sid not in _SESSIONS:
        _SESSIONS[sid] = Engine(store=_STORE)
    return _SESSIONS[sid]


def bootstrap_payload() -> dict:
    return {
        "examples": EXAMPLES,
        "llm_available": llm.available(),
        "counts": {name: len(rows) for name, rows in _STORE.tables.items()},
        "session_id": secrets.token_hex(8),
    }


def ask_payload(question: str, sid: str | None, use_llm: bool) -> tuple[dict, int]:
    question = (question or "").strip()
    if not question:
        return {"error": "empty question"}, 400

    engine = _engine_for(sid or "default")
    try:
        answer = engine.ask(question)
    except Exception as exc:  # never 500 the UI on a bad parse
        return {
            "mode": "refuse",
            "text": f"The assistant could not handle that input ({exc}).",
            "citations": [],
            "flags": [],
            "prose": None,
            "notes": [],
        }, 200

    prose = None
    if use_llm and answer.mode == "answer" and llm.available():
        try:
            prose = natural_text(llm.compose(question, answer.render()))
        except Exception as exc:
            prose = f"(Claude layer unavailable this turn: {exc})"

    return {
        "mode": answer.mode,
        "answer": natural_text(answer.prose),
        "detail": natural_text(answer.text),
        "citations": answer.citations,
        "flags": [natural_text(flag) for flag in answer.flags],
        "prose": prose,
        "notes": engine.session.all(),
    }, 200
