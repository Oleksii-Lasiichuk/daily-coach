# Plan 06 — v4: clarity, one home per item, editing, quick wins

CRISP-DM phase: 6. Deployment (UI, after a usability review), 4. Modeling (agent rules, new
code-only components), 5. Evaluation (prompt-injection eval, re-runs).
Status: requested by Oleksii on 2026-11-15 ("plan and execute all those fixes").

## Goal
The v3 review found that the app works but is hard to read. Numbers have no labels, the same
item lives on two pages, the settings page looks like an admin console, and wrong estimates
can't be fixed. v4 fixes that and adds the cheap features a runner asks for first: quick logs,
habits, pain trend, patterns, fuel, race countdown, shoe km, weight goal and weather.

## Decisions

| Topic | Decision |
|---|---|
| Plan source | Garmin Coach is optional. Planned sessions come from three places: a screenshot or chat (Garmin Coach or any plan), the intervals.icu calendar (synced), or nothing. Then the coach plans from goals and load. Setup asks "Do you follow a plan?". UI says "Your plan" |
| One home per item | **Training**: goals, races, gear (editable, race countdown, shoe km). **Health**: conditions, injuries, medication, lab results (editable), pain trend, patterns, weight goal. **Memory** (was Knowledge): instructions, food and training preferences (incl. diet), life, notes, files. **Settings** (was Profile): you, language, time zone, location, all reminders, intervals.icu. Model, key and usage are under **Advanced**. Console links and the app's credit are **admin-only** |
| Names | Nutrition everywhere. Day types: Recovery / Easy / Normal / Push (one map). README matches the UI |
| Metric labels | Tiles say "Sleep 7.2 h · usual 7.0" and have a "What these mean" expander (HRV, resting HR, form = fitness − fatigue). Load has a tooltip |
| Why today | The day card has "Why?" with every reason and its evidence. Buttons say what they do ("Check my day"). Past days get "Assess this day" |
| Chat controls | No top bar. A ChatGPT-style menu in the composer: Auto · Training · Nutrition · Health, each with one line, plus a "Think harder" switch. No question chips. Day 0 shows example logs that fill the box |
| Progress | Honest: "Working… 6 s" instead of invented steps |
| Editing | Meals: ×½, ×2, set kcal, rewrite text (re-estimated). Past days: add an entry, assess, edit or delete entries. Time zone is editable |
| Photo meals | The coach first lists what it sees with grams and asks "Right?", then logs |
| Quick log | Water, coffee, tea, beer: one tap, fixed values, Undo |
| Habits | Your own checklist on Today (stretching, 2 L water, meds, bed by 23:00) |
| Pain | Health plots pain 0–10 per body part (from the logs) with a 14-day trend |
| Patterns | Computed in code (no LLM): next-morning HRV, resting HR and sleep after tagged days (alcohol, late meal, high caffeine, short sleep) vs other days, only with ≥ 3 vs ≥ 5 nights |
| Weekly review | Journal shows this week vs last; a Sunday push |
| Session card | "Instead of: <your plan>" and Fuel before/during/after (rules: carbs g/kg and g/h by length) |
| Weather | Open-Meteo forecast and air quality (no key) for the city set in Settings; given to the planner |
| Sync | The 15-minute tick syncs intervals.icu hourly per user (wellness, activities, plan) |
| Push answers | Morning push has buttons: slept badly / OK / great → logged without opening the app (where the OS shows buttons) |
| Language | UI in English or Ukrainian (Settings and the side bar). Chat and your data are not translated |
| Files | Up to 25 MB per file (Cloud Run's request limit is 32 MB). Step 4 explains what a ChatGPT export is and how to get it |
| Prompt injection | Files, tool results and weather are data. `update_profile` only takes known keys (no `instructions`). File facts still need your OK; the watch still needs Apply. New eval: injected tool results must not trigger write tools |

Not done: Google Calendar sync (see the answer in chat: ICS feed is easy, two-way needs OAuth
verification), a coach-for-many-athletes product.

## Steps
1. Migration 005 (lang, habits, habit checks) → verify: `uv run python -m app.migrate`.
2. i18n helper + date filter → verify: a page renders in both languages.
3. Templates and routes per the table → verify: tests + screenshots at 375/1280, light/dark.
4. Backend: patterns, fuel, weather, plan sync, tick, push actions, agent hardening.
5. Evals: new `run_injection`; re-run C1, C6 and C8 → results recorded in `05-evaluation.md`.
6. Deploy, migrate prod, smoke test.

## Acceptance criteria
- [x] Every number on Today and Training has a label or an explanation.
- [x] Each item kind is editable on exactly one page.
- [x] A meal and a past day can be corrected.
- [x] UI switches to Ukrainian.
- [x] Injection eval: no write tool called on injected content.
- [x] Tests pass; deployed.

## Result (2026-11-15)

**Built:** everything in the table above.
- **New modules:** `app/patterns.py`, `app/weather.py`, `app/i18n.py` + `app/i18n_uk.json`
  (539 strings).
- **Shared partials:** `partials/items.html` (one item editor for three pages) and
  `partials/log_row.html` (meal and entry edits).
- **Pages:** Memory (was Knowledge), Settings (was Profile).
- **Database:** migration 005 (language, habits).
- **Settings:** `ADMIN_EMAILS`.

**Verified:**
- 34 tests pass (8 new: patterns, quick log and edits, fuel, safe redirects, profile key
  allow-list, untrusted wrapper, language switch, and isolation for the new endpoints).
- All pages render for a seeded demo user at 1280 px (light) and 375 px (dark, Ukrainian), with
  no sideways scroll.
- Real LLM calls: adding to a past day, assessing a past day, and a chat turn (gear + weight +
  coffee).
- Evals:
  - prompt injection: 0/10 attacks succeeded; utility 1.0;
  - C1: 0.83;
  - C8: 1.00;
  - C6: 100% valid after a retry, judge 3.94.
- Deployed: revision coach-00008 and later. `/status`, `/sw.js` and the cron tick respond.

**Not verified:**
- the photo-confirmation flow with a real meal photo;
- push answer buttons on a real Android phone;
- weather with a real city in production;
- the intervals.icu calendar sync against a real calendar with workouts;
- the Ukrainian wording, which a native speaker should read.

**Deviation:** in one chat test the coach saved the new shoes twice, then ended one itself.
Duplicate detection is exact-text only.
