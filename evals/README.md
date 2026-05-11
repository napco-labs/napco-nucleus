# NAPCO Nucleus — eval harness

The minimum thing that turns "I think the identifier got better" into a number.

## What it does

For each fixture case in `evals/cases/<name>/`:

1. Archive your current pull session (so production state is safe).
2. Drop the case's `session.docx` into the live session path.
3. Run `agent.py --task verify_session` with eval-mode env vars set, so the LLM identifies requirements but does NOT touch `requirements_seen`, the activity log, or send an email draft.
4. Read the verification doc's JSON sidecar (the structured requirements list).
5. Score the predicted list against `expected.json` using Claude Haiku as a judge (exact-match / partial-match / extra / missed).
6. Append the scores to `evals/results/<timestamp>.json` for trending.

## Layout

```
evals/
  cases/
    <case_name>/
      session.docx        # input fixture (committed, ~30-80 KB)
      expected.json       # gold-standard requirement list
      build_fixture.py    # optional — regenerates session.docx
  results/                # per-run JSON output (gitignored except .gitkeep)
  run.py                  # orchestrator (entry point: py -3 -m evals.run)
  score.py                # LLM-as-judge scorer
```

## expected.json format

```json
{
  "case_name": "example_operator_management",
  "description": "Single explicit client requirement in an email PDF.",
  "expected_requirements": [
    {
      "title": "Operator Management with CRUD, search, RBAC, audit logging",
      "summary_keywords": ["operator", "CRUD", "RBAC", "audit"],
      "expected_min_confidence": 0.80,
      "expected_source_id_pattern": "email/.*/.+"
    }
  ],
  "notes": "Other sections should be classified as noise."
}
```

`expected_requirements` is a list. Each item lists:

- `title` — the canonical requirement statement (Haiku judges semantic match against this).
- `summary_keywords` — words/phrases that should appear in the predicted summary (case-insensitive substring match).
- `expected_min_confidence` — flag if the LLM's reported confidence falls below this floor.
- `expected_source_id_pattern` — regex the predicted Source IDs must satisfy (so you can assert "this requirement should cite an email Source ID").

## Running

```powershell
# Run all cases
py -3 -m evals.run

# Run one case
py -3 -m evals.run --case example_operator_management

# Skip the LLM identify step — score whatever JSON is already at
# data/requirements/Requirements Verification <today>.json
# Useful for iterating on the scorer without re-paying for identify.
py -3 -m evals.run --no-replay
```

## Output

Each run appends one row to `evals/results/<timestamp>.json`:

```json
{
  "timestamp": "2026-05-11T15:45:00",
  "git_commit": "<short-sha>",
  "cases": [
    {
      "case_name": "example_operator_management",
      "predicted_count": 1,
      "expected_count": 1,
      "matches": [
        {
          "expected_title": "Operator Management...",
          "predicted_title": "Operator Management with CRUD...",
          "kind": "exact_match",
          "predicted_confidence": 0.95
        }
      ],
      "missed_recall": [],
      "extras": [],
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0,
      "citation_correctness": 1.0,
      "mean_predicted_confidence": 0.95
    }
  ],
  "summary": {
    "case_count": 1,
    "mean_precision": 1.0,
    "mean_recall": 1.0,
    "mean_f1": 1.0,
    "mean_confidence": 0.95
  }
}
```

## Adding a new case

1. Create `evals/cases/<your_case_name>/`.
2. Either:
   - Copy a real `data/requirements/sessions/current.docx` from a past run into the case folder, OR
   - Write a `build_fixture.py` that constructs the session doc programmatically with `tools._session_doc.append_section()` and run it once.
3. Hand-write `expected.json` listing the requirements you believe a perfect identifier should extract.
4. Run `py -3 -m evals.run --case <your_case_name>` and inspect the result.

## Calibration loop

Over time the goal is: **predicted confidence tracks reality.** When the LLM says 0.95, ~95% of those predictions should be exact matches. Use a series of run results to plot stated-confidence vs. actual-precision, and tune the rubric in `prompts/verify_session.md` accordingly.

## Cost note

Each case costs one identify run + one Haiku scoring run. Roughly $0.01-$0.05 per case in 2026 pricing. Five cases × one run a week is well under a dollar a month.
