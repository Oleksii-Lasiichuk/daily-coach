# 02 — Data understanding

CRISP-DM phase 2. What data the system sees, where it comes from, and what we learned by
looking at it.

## Runtime data (per user)

| Source | What | Size / quality | Notes |
|---|---|---|---|
| Chat messages | Free text in Ukrainian, English or mixed; typos, slang, relative dates ("вчора ввечері") | A few messages a day | The main NLP input |
| intervals.icu athlete | Sex, birth date, height, weight, time zone, per-sport LTHR, max HR, HR zones, threshold pace, FTP | One record | Checked against a real response on 2026-11-14. Height, birth date and gear were empty for the author, so the interviewer (C0) asks for them |
| intervals.icu wellness | Daily HRV, resting HR, sleep (seconds, score), CTL/ATL (fitness/fatigue), steps, VO2max | 1 row per day | Synced from Garmin. Sleep can be wrong (3.6 h measured vs 6 h reported on the same night), so the user's own words count more |
| intervals.icu activities | Type, distance, time, load, HR | ~5 a week | Types are open-ended (Run, Swim, WeightTraining, Ride, Badminton…), so sports are not hard-coded |
| intervals.icu events | Planned workouts | — | **0 events in ±60 days: Garmin Coach plans never reach intervals.icu.** The planned workout therefore comes from the user's words (`planned_workout` log) |

**Finding that changed the design:** HR zones arrive as a list of zone *upper limits*
(`[123, 143, 164, 184, 204]`). The LLM misread it (see 05-evaluation, C8). We now store explicit
ranges (`Z2: 124-143`).

## Existing datasets considered

| Dataset | Use | Decision |
|---|---|---|
| NutriBench v2 (Hugging Face `dongx1997/NutriBench`, 15,617 meal descriptions with carbs/fat/energy/protein, 24 countries, CC BY-NC-SA 4.0) | Benchmark for C3 | **Used:** 50-meal stratified sample (20 US natural, 10 US metric, 20 other countries) |
| USDA FoodData Central | Per-100 g food values | Used as the reference for the Ukrainian meals; planned as a lookup tool for C3 |
| Public Ukrainian chat / health-logging corpora | C1/C2 training or eval | None found that matches personal training logs; wrote synthetic cases instead |
| The author's ChatGPT "life & sports" history | Realistic messages | Not used for the submission (personal data; the repo is public) |
