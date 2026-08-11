# Owners Forum Case Study Submission

This submission includes a runnable prototype, the seven requested notes, the
provided CSV dataset, and a small regression suite.

## What is included

- Runnable prototype in `solution/`
- Seven deliverable notes in `solution/NOTES.md`
- Short implementation explanation in `EXPLANATION.md`
- CSV dataset in `data/`
- Reconstructed `policies.md` from the PDF summary
- Regression evaluation in `solution/eval/run_eval.py`

## Requirements

- Python 3.10 or newer
- No required third party packages for the core prototype
- Optional: `anthropic` only if you want the extra prose rewrite layer

## Quick start

Create and activate a virtual environment if you want one:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install project requirements:

```bash
pip install -r requirements.txt
```

Run the web app:

```bash
python3 -m solution.web.server
```

Then open:

```text
http://127.0.0.1:8765/
```

## Other ways to run it

Run the CLI:

```bash
python3 -m solution.assistant.cli
```

Run the evaluation:

```bash
python3 solution/eval/run_eval.py
```

Current evaluation status: `52/52` checks passing.

## How the solution is implemented

The core prototype is deterministic and does not require an API key.

It works by loading the CSV files into memory, resolving entities and intent,
retrieving matching rows, applying policy rules in code, and then returning one
of four response modes: `answer`, `clarify`, `refuse`, or `escalate`.

I chose this approach because the dataset is small, structured, and closed,
while the task requires exact citations and explicit privacy handling. In that
setting, deterministic retrieval plus code enforced policy is easier to audit
and defend than making a model part of the core decision path.

The optional model layer in `solution/assistant/llm.py` is only a final prose
rewrite step. It does not do retrieval or policy decisions, and the system runs
fully without it.

For a short implementation overview, see `EXPLANATION.md`.

## When I would introduce a model

If the system grew into a larger graph, a broader network of entities, or a mix
of structured and unstructured sources, I would introduce a model for tasks
such as query planning, fuzzy request mapping, evidence summarization, and
multi step reasoning over larger result sets.

Even then, I would keep retrieval, policy checks, and citation validation in
deterministic code as the trusted backbone.

## Where session notes are stored

Session notes are stored only in memory.

Each browser session gets its own `Engine`, and each `Engine` owns a
`SessionStore` that keeps notes in a local list. Notes are not written to the
CSV files, not persisted to disk, and they are cleared when the server process
restarts.

## Project layout

```text
README.md
EXPLANATION.md
requirements.txt
Case-Study-Briefing_Senior-AI-Engineer.pdf
policies.md
data/
  accounts.csv
  activities.csv
  event_attendance.csv
  events.csv
  people.csv
  relationships.csv
  sources.csv
solution/
  NOTES.md
  assistant/
    cli.py
    data.py
    engine.py
    llm.py
    narrate.py
    policy.py
    resolve.py
    session.py
  eval/
    run_eval.py
  web/
    index.html
    server.py
```

## Notes for review

- The app loads CSVs from `data/` by default.
- The web app includes the 15 case study prompts as quick examples.
- The prototype runs on the Python standard library only unless the optional
  Anthropic layer is enabled.
- The optional prose layer is gated after policy checks, so it never sees
  withheld content.

## Optional prose layer

The prototype is fully usable without any external model dependency. If you
want to enable the optional prose rewrite layer:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=YOUR_KEY_HERE
python3 -m solution.assistant.cli
```

Then use `/llm on` inside the CLI.

## Known input gap

The briefing references `policies.md`, `data_dictionary.md`, and `prompts.md`
as source files. In this workspace, `policies.md` has been reconstructed from
the PDF summary page, while `data_dictionary.md` and `prompts.md` were not
provided. The executable rule layer lives in `solution/assistant/policy.py`.
# theOwnersForumTask
