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
- **Facts:** durable knowledge in 8 categories, shown and editable on the Memory page.
- **Profile:** key/value with a source (`intervals` / `user` / `ai`). The interviewer decides
  which fields matter, so the columns are not fixed.
- **Wellness:** turned into a compact summary with 7-day baselines computed in code (not by the
  LLM): `{today, baseline_7d, activities_14d}`.
- **HR zones:** explicit ranges. Pace is shown per km for running and per 100 m for swimming.

## B3 (2026-11-20): synthetic lab sheets for C10

No public dataset has Ukrainian lab sheets with labels, and real reports are personal health
data, so `evals/make_c10_labs.py` draws 15 sheets with fake values (seeded, reproducible):
5 clean PNG, 5 "phone photos" (tilt ±4°, shadow gradient, blur, JPEG), 5 text PDFs
(matplotlib, real text layer). Three made-up table layouts in the style of common UA lab forms
(no real forms or logos), 9 Ukrainian and 6 English sheets. Each has 18 catalogue markers and 2
unknown ones (procalcitonin, homocysteine, anti-TPO), ~15 % low and ~15 % high values, some
units the catalogue must convert (vitamin D in ng/mL, Hb in g/dL, glucose in mg/dL…), lab ranges
slightly different from the catalogue defaults (so "printed range first" is tested), and
distractors: patient "Тест Тестенко" / "Test Testenko", birth date, order number, doctor, a
later "issued" date and a comment paragraph. Labels (`evals/data/c10_labs.jsonl`) are written by
the generator from the true values; 3 images and 2 PDFs were checked by eye.
## C11 spend category set (plan 11 B4)

`evals/make_c11_spend.py` writes 161 synthetic card payments (`evals/data/c11_spend.jsonl`):
chains in Ukrainian and Latin spellings, misleading MCCs (Glovo with a grocery MCC), unknown
local cafés and shops, race-registration sites, sports-nutrition shops, pharmacies and labs,
transfers, cash and income. Labels are by hand (one of the 22 fixed categories).
It also draws 15 receipt images with PIL in a Ukrainian fiscal-receipt layout with fake shop
names (`evals/data/c11_receipts/`), with line labels, the total and whether a "Log as a meal /
fuel" offer is expected. The first 10 are the accuracy set; all 15 are used for the offer check.
**Bias:** the merchant rules and the set were written in the same session, so the rules-only
number is optimistic (see 05). Labels are not yet reviewed by Oleksii.
