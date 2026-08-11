# Policies

Reconstructed on August 11, 2026 from the summary on page 6 of
`Case-Study-Briefing_Senior-AI-Engineer.pdf`.

This is not the original source file referenced by the brief. It captures the
policy summary shown in the PDF so the workspace has an explicit policy file.

## Grounding

- Never invent facts, dates, attendance, revenue, or relationships.
- If the dataset does not support an answer, say so directly.

## Conflicts

- When records disagree, flag the conflict and cite both sides.
- Prefer newer evidence, but do not silently drop older evidence.

## Contact Visibility

- `shareable_business`: business email and phone may be shown.
- `email_only`: email may be shown; phone must not be shared.
- `restricted`: neither may be shown; say permission is required.
- `internal_only`: not shown externally; summarize as internal-only.

## Sensitive Topics

- Succession, ownership transition, and family or health matters require:
  cited answers, reliability labels, and a human-review flag for rumors or
  restricted notes.

## Ambiguity

- If a request could refer to multiple people, accounts, or events, ask for
  clarification or present the plausible options with citations.
