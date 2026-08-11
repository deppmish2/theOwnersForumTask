# Deliverable Notes

The seven notes from page 8 of the briefing. Bullets, not prose — judgment over
documentation length.

---

## 1. Architecture note

- Structured retrieval over the 7 CSVs: resolve entities → join rows → policy gate → grounded answer with citations.
- Deliberately not vector RAG: the dataset is small and ID-driven, so deterministic joins are simpler and more exact.
- The LLM layer is optional and post-gate only; it rewrites style, but does not retrieve or decide policy.
- `policy.py` is the single rules file for contact visibility, sensitivity, staleness, and evidence labels.

## 2. Context / memory note

- Context is session-scoped and in-process only: last resolved entities plus an in-memory note store.
- Pronoun carry-over happens only when the new turn resolves nothing and the wording clearly refers back.
- Clarify follow-ups resume the original question when the user answers with a record id or short disambiguator.
- Notes that match no dataset entity stay unlinked rather than being attached by guesswork.

## 3. Retrieval strategy note

- All CSVs are loaded into memory with primary-key indexes and explicit join helpers, so retrieval paths stay readable and testable.
- Entity resolution is tiered: record ids first, then exact names, then limited partial-name fallbacks.
- Ambiguity is a first-class result; the assistant returns options and asks instead of picking one.
- Thematic questions use structured filters, negation checks, and evidence quality checks rather than semantic similarity.

## 4. Session-notes note

- Session notes live in a separate append-only store and are never written back into the CSVs.
- They use a separate citation namespace (`SN001`, `SN002`, …) and always render as session-only, unverified material.
- Notes are surfaced alongside dataset facts, not merged into them.
- When possible, a note links to resolved entity ids; otherwise it is stored unlinked.

## 5. Decision-logic note

- `answer`: enough grounded evidence, no unresolved ambiguity, citations attached to each claim.
- `clarify`: multiple matching people/accounts/events, so the assistant shows options and waits.
- `refuse`: restricted contact detail or unsupported claim; it states why rather than going quiet.
- `escalate`: sensitive or restricted material is in scope, so content is withheld and human review is flagged.
- Cross-cutting rule: stale, low-reliability, unverified, or explicitly denied evidence is shown with caveats instead of being silently dropped.

## 6. Evaluation plan

- The 15 provided prompts are the fixed regression set, and every run writes a transcript for review.
- 52 automated checks cover privacy, citation behavior, ambiguity, thematic filtering, and RSVP/contact edge cases.
- The suite is aimed at judgment failures, not just crashes: wrong-yet-plausible answers are the main target.
- With more time I’d add per-claim citation audits, prompt-injection tests, and a small human-rated usefulness pass.

## 7. Privacy & limitations note

- Contact visibility is enforced in code before composition, so restricted details never depend on prompt compliance.
- Restricted records are filtered before the optional LLM layer, so withheld content never enters model context.
- `policies.md` is reconstructed locally from the PDF summary, but `data_dictionary.md` and `prompts.md` are still missing source-of-truth inputs.
- This is a trusted-internal prototype, not a multi-tenant system; real deployment would need caller auth and role-aware policy.
- Intent detection is still keyword-based, so unusual phrasing should eventually move to a classifier with confidence thresholds.
