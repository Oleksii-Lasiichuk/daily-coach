# 03 — Data preparation

CRISP-DM phase 3. How the eval data was built. There is no training data: the components are
prompted LLMs, so the data work is about evaluation and about how runtime data is represented.

## Eval sets (`evals/data/`)

| File | Cases | How it was made |
|---|---|---|
| `c7_safety.jsonl` | 40 (20 red flags) | Hand-written. Covers all 7 red-flag categories plus hard negatives (DOMS, hangover, "what if I get chest pain?") |
| `c1_router.jsonl` | 60 | Hand-written. Single- and multi-intent messages, UA/EN, short answers ("так", "Skip it") |
| `c2_extract.jsonl` | 40 (51 gold events) | Hand-written with a fixed "now" (Sat 2026-11-14 09:30 Kyiv), so relative dates have one right answer. Two ambiguous cases were reworded after review |
| `c3_nutrition.jsonl` | 60 | 50 NutriBench meals (seed 42, stratified) + 10 Ukrainian meals with gram amounts. Their gold is computed from a per-100 g table that is stored with the data |
| `c5_daytype.jsonl` | 30 | Day scenarios (wellness vs 7-day baseline, logs, facts). 10 recover, 10 easy, 5 normal, 5 push. 3 have no device data |
| `c6_planner.jsonl` | 20 | Scenarios with a day type, the Garmin Coach plan, injuries, requests and two athletes (runner/swimmer, cyclist). Each has an `expect` note for the judge |
| `c0_interview.jsonl` | 5 athletes | Hidden full profiles, part of them prefilled; a simulated user answers from the hidden profile |
| `c8_reply.jsonl` + `c8_context.json` | 15 | Questions over one fixed context; 4 ask for data that is not there |

| `c4_export.md` + `c4_planted.jsonl` | 1 file (36 k chars), 24 planted facts, 24 questions | `evals/make_c4_export.py`. The planted facts and questions are fixed in code; the LLM only writes the surrounding dialogue, and each fact sentence is checked to be verbatim, so the gold location is exact |

`evals/make_sets_c6_c0_c8.py` builds the larger sets from code, so the cases are easy to review in
a diff.

## Runtime representation

- **Logs:** typed events (`kind`, `day`, optional time, kind-specific fields).
  - "Day" is the date in the user's time zone; the time is stored in UTC.
  - Sleep is stored on the day you wake up.
- **Facts:** durable knowledge in 8 categories, shown and editable in About me.
- **Profile:** key/value with a source (`intervals` / `user` / `ai`). The interviewer decides
  which fields matter, so the columns are not fixed.
- **Wellness:** turned into a compact summary with 7-day baselines computed in code (not by the
  LLM): `{today, baseline_7d, activities_14d}`.
- **HR zones:** explicit ranges. Pace is shown per km for running and per 100 m for swimming.
