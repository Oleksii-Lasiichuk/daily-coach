---
name: eval
description: Run a component eval (or all of them), record the result and update the report. Use for /eval, after changing a prompt, model or component, or before saying a component is done.
---

Run the eval for the component named in the user's message (C0–C8, injection, e2e, or "all").

## Steps

1. Find the script: `evals/run_<component>.py` (`run_all.py` for all, `run_e2e.py` for the
   agent end to end, `run_injection.py` for prompt injection). Read its docstring: what it
   scores and what it needs (e2e needs ENV=dev for the demo athlete).
2. Note the current numbers from `evals/results/<component>.json` before running.
3. Run it: `uv run python -m evals.run_<component>`. Long runs (> 2 min) in the background.
4. Run `uv run python -m evals.stats` to refresh the 95% intervals.
5. Compare with the numbers from step 2. A change smaller than one case (1/n) is noise; say so.
6. Read every failure in the result file. Group them by cause, not by case.
7. Update `docs/report/05-evaluation.md`: the row in "Current results", and a short note in
   "What the errors show" if the cause is new. Update `docs/report/README.md` only if a headline
   number changed. Never copy a number by hand from memory; take it from the result file.

## Report back

- Before → after, with n and the interval.
- Failure groups with one example each.
- What the eval does not cover.
