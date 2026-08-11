"""Optional Claude composition layer.

The deterministic engine produces the answer, evidence, and policy
decisions. When an Anthropic credential is available, this layer rewrites
the answer as natural prose — but the model only ever sees the already
policy-gated material, so it cannot leak what the gate withheld, and it is
instructed to keep every citation and flag intact.

The prototype is fully functional without this layer (and without the
`anthropic` package installed).
"""

from __future__ import annotations

import os

MODEL = "claude-opus-5"

SYSTEM = """You rewrite a structured, policy-checked answer from a membership-data
assistant into clear natural prose for an internal team member.

Hard rules:
- Use ONLY facts present in the structured answer. Never add names, dates,
  numbers, or claims from outside it.
- Keep every citation id (e.g. ACT009/S011, AT011, SN001) attached to the
  claim it supports.
- Keep every policy label: public vs internal vs restricted, reliability,
  session-note markers, caveats, and human-review flags.
- If the structured answer refuses, clarifies, or escalates, your prose must
  do the same — do not soften a refusal into an answer.
- Write like a calm teammate in natural conversation.
- Do not use any hyphen or dash characters.
- Be concise."""


def available() -> bool:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def compose(question: str, rendered_answer: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": (f"User question:\n{question}\n\n"
                        f"Structured, policy-checked answer to rewrite:\n{rendered_answer}"),
        }],
    )
    if response.stop_reason == "refusal":
        return rendered_answer  # fall back to the deterministic rendering
    return "".join(b.text for b in response.content if b.type == "text")
