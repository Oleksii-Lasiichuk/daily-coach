---
name: implement
description: Implement a plan from docs/plans/ (or a small clear task) step by step, verifying each step. Use for /implement or when asked to build what was planned.
---

Implement the plan or task named in the user's message.

## Steps

1. Read the plan, `AGENTS.md`, and the code it touches. No plan and the task is
   non-trivial → suggest `/plan` first.
2. Do the steps in order. After each step run its `verify` check. Failed → fix
   before moving on; do not skip.
3. Follow `AGENTS.md` style: simplest correct code, surgical changes, no extras
   beyond the plan. Need to deviate → stop, say why, ask.
4. Run the component's eval if the plan has one; save results in `evals/`.
5. Tick acceptance criteria in the plan. Add a `## Result` section: what was done,
   eval numbers, deviations, known limitations.
6. Update `docs/report/` with decisions and results for the CRISP-DM phase.

## Report back

- What changed (files).
- What was verified and how (commands, metrics).
- What is not verified or still open.

Never claim something works without running it.
