---
name: plan
description: Write a short implementation plan to docs/plans/ before non-trivial work (new component, data pipeline, eval, UI). Use for /plan or when asked to plan.
---

Write a plan for the task in the user's message. Do not write code.

## Steps

1. Read `AGENTS.md`, relevant code, data and existing plans in `docs/plans/`.
2. If the goal or scope is unclear, ask 1–3 focused questions first.
3. Write `docs/plans/<NN>-<slug>.md` (`NN` = next number) with the template below.
4. Reply with the path and a 3–5 line summary. Stop; wait for the user to say go.

## Template

```markdown
# <Title>

CRISP-DM phase: <phase>

## Goal
What we build and why, in 2–4 sentences.

## Scope
- In: ...
- Out: ...

## Assumptions / open questions
- ...

## Design
Components touched: purpose, input, output. Model and tool calls. Small diagram if useful.

## Steps
1. <step> → verify: <check>
2. <step> → verify: <check>

## Evaluation
Metric per component, eval data, how to run, what counts as good.

## Acceptance criteria
- [ ] ...
```

Keep it short. Prefer the simplest design that meets the goal; name the main
alternative and why it lost in one line.
