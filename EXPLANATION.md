# Implementation Explanation

## Core approach

This prototype is not built as an LLM driven system. The main assistant is a
deterministic, code based layer over a closed CSV dataset, so it does not need
an API key to run.

The current implementation is aligned against the recruiter provided
`policies.md` and `data_dictionary.md`.

The main flow is:

1. Load the seven CSV files from `data/`
2. Resolve the user intent and any mentioned people, accounts, or events
3. Retrieve matching records through explicit joins and filters
4. Apply privacy, sensitivity, and evidence rules in code
5. Return one of four modes: `answer`, `clarify`, `refuse`, or `escalate`

## Main files

- `solution/assistant/data.py`
  Loads the CSV files into memory, validates the expected schema, and builds
  simple indexes.

- `solution/assistant/resolve.py`
  Detects intent and resolves entities such as people, accounts, and events.

- `solution/assistant/engine.py`
  Orchestrates retrieval, policy checks, and final answer composition.

- `solution/assistant/policy.py`
  Central rule layer for contact visibility, sensitive topics, restricted
  records, stale evidence, and reliability labels.

- `solution/assistant/session.py`
  Keeps temporary session notes separate from the dataset.

- `solution/web/server.py`
  Serves the local web interface and creates one assistant session per browser
  session id.

## Optional model layer

There is one optional model integration in `solution/assistant/llm.py`.

That layer is only a prose rewrite step. It does not retrieve data, decide the
answer, or apply policy. The prototype works fully without it. If no API key is
present, the system still runs normally.

## Where session notes are stored

Session notes are stored only in memory.

More precisely:

1. `solution/web/server.py` keeps a process local `_SESSIONS` dictionary
2. Each `session_id` gets its own `Engine`
3. Each `Engine` has its own `SessionStore`
4. `SessionStore` keeps notes in the in memory list `self._notes`

That means:

- Notes are not written into the CSV files
- Notes are not persisted to disk or a database
- Notes stay scoped to that server process and that browser session
- Notes are lost when the server restarts

## Why this design

- The dataset is small, structured, and closed world, so deterministic joins are
  simpler and easier to audit than semantic retrieval.
- Policy decisions are easier to review when they live in code instead of in a
  prompt.
- The provided `policies.md` and `data_dictionary.md` map cleanly onto explicit
  code paths, which keeps behavior testable and reviewable.
- Keeping session notes in memory avoids mixing temporary user statements with
  the source dataset.

## When I would bring in a model

If the problem expanded into a larger graph, more varied language, and a mix of
structured and unstructured data, a model would become more useful.

In that setting we would use a model for:

1. Translating open ended requests into structured query plans
2. Mapping fuzzy user phrasing onto graph entities and relationships
3. Ranking or summarizing larger evidence sets
4. Handling more complex multi step follow ups

We keep policy enforcement, source grounding, and final citation
checks in deterministic code.
