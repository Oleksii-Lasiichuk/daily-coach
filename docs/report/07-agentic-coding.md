# 07 — Using the AI coding assistant

How the system was built with Claude Code: what goes into its context, the rules that control
quality, the loop each change goes through, and what went wrong.

## What the assistant always reads

| Layer | File | Why |
|---|---|---|
| Project rules | `AGENTS.md` (loaded through `CLAUDE.md`) | Project, stack, grading criteria, CRISP-DM, "how to work", security rules, what "done" means, git rules |
| On demand | `docs/design-guidelines.md` | Security and UI rules, read before UI, auth or data work |
| The task | `docs/plans/NN-*.md` | Each non-trivial change starts as a plan with steps and a check per step |
| Skills | `.claude/skills/` | Repeatable procedures (below) |
| Never | `.env`, `data/private/`, real exports | Secrets and personal data stay out of the context and the repo |

**Skills:**
- `/plan`: writes a plan (goal, scope, design, steps with a check each, eval, acceptance
  criteria) and stops until I say go.
- `/implement`: builds a plan step by step, runs each check, records the result in the plan
  and the report.
- `/explain`: explains code or a concept, so I understand what was built.
- `/eval` (v6): runs a component eval, refreshes the intervals, compares with the last run and
  updates the report from the result file.
- `/ui-check` (v6): checks a page at 375 and 1280 px, light and dark, in both languages, on the
  demo athlete.
- `langfuse`: the official Langfuse skill, for tracing and datasets.

## The loop

1. **Plan** (`/plan`): the plan names the CRISP-DM phase and how each step is checked.
2. **Build** (`/implement`): small steps; tests and lint after each.
3. **Evaluate**: the component's eval, compared with the previous run.
4. **Look at it**: the running app at phone and desktop width.
5. **Report**: "what changed, what was verified, what was not". This line is in AGENTS.md
   because the assistant otherwise says "done" too early.

Seven plans went through this loop (`docs/plans/01` to `07`), plus this v6 round, which started
from an independent review of the whole app by a second model.

## What went wrong, and what it became

Every real failure became a rule, a validator, a test or an eval case, so it can't come back
silently.

| What went wrong | Found by | Became |
|---|---|---|
| Reasoning tokens used up `max_tokens`; answers came back cut off | First end-to-end test | Higher limits for reasoning models; a cut-off reply is retried with more room (`app/llm.py`) |
| 4 of 15 coach answers were empty (tools in the prompt, none in the eval) | C8 eval | One retry without tools in the app; the eval says tools are unavailable |
| HR zones read as lower limits (zone 2 = 143–164 instead of 124–143) | C8 eval | Zones stored as explicit ranges; a data fix, not a prompt fix |
| "50 min threshold run" with only 15 min of steps | C6 eval | Validator rule "a main set is required"; prompt rule "steps add up" |
| The coach saved the same shoes and watch twice | Using the app | `tidy.near_duplicate` blocks near-identical items; `test_near_duplicates_are_not_saved_twice` |
| A file could ask the coach to change its own instructions | Security review | `update_profile` accepts 10 fixed keys; file excerpts wrapped as untrusted; injection eval |
| "5 kg of sushi" depended on the model noticing | Using the app | Limits in code (`implausible()`); `test_impossible_amounts_are_not_logged` |
| `watch_cue` removed the letter "x" ("rela ed") | Unit test | Only digit×digit patterns are stripped; test kept |
| Sleep stored on the wrong night ("Вчора 2 пива, спав 5 годин") | Review of the app | Prompt rule; 3 new C2 cases |
| "11% higher sleep after a late meal" on random data | Review of the app | Welch t ≥ 2.5; a test on 50 random logs |
| A rest day was badged "ready to send" | Review of the app | Badge by action |
| The coach couldn't see race dates (item details missing from its context) | New end-to-end eval | Details added to the context; e2e case `next_race` |
| Numbers disagreed between report files; the diagram showed v1 | Review | One report README; numbers come from result files (the `/eval` skill) |

## What the assistant did badly

- **Over-scoping.** Asked for fixes, it also added features. The "no speculative features" rule
  in AGENTS.md reduced this but didn't stop it.
- **Stale documents.** Code moved faster than the report: the review found six places where
  the docs described an older version.
- **Claims without checks.** Left alone, it reports work as done from the code alone. AGENTS.md
  asks for screenshots at two widths and two themes and a "not verified" list; the `/ui-check`
  skill turns that into steps.
- **Its own eval sets.** The cases were written with the assistant that built the system. Using a
  different model family as the judge, keeping every failure in the result files, and adding
  confidence intervals limit this, but a second human annotator would be better.

## What I would add next

- A `/slop-check` skill: the AI-look checklist (equal cards everywhere, helper text under every
  control, generic advice sentences, statistics on tiny samples).
- A pre-commit hook that runs ruff and the fast tests.
- A held-out set written by me, not the assistant, for C2 and C5.
