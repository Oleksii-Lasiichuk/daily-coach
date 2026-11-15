# Daily Coach

A personal coach you talk to in Ukrainian or English. You tell it how your day went (sleep,
food, drinks, pain, mood, what your plan says), and it:

- logs that as dated, structured events, with energy, macros and 16 nutrients for meals;
- reads your sleep, HRV, resting HR and training load from intervals.icu (synced hourly);
- decides today's **day type** (Recovery / Easy / Normal / Push) and shows every reason;
- proposes an adapted workout that, after you press **Send to watch**, goes to your
  intervals.icu calendar and from there to your Garmin watch. It works with or without a plan:
  Garmin Coach (screenshot), a plan on your intervals.icu calendar, or none;
- reads your own `.txt` / `.md` / `.json` exports (e.g. ChatGPT history), proposes facts with the
  quote they came from, and looks things up in them when it answers or plans;
- finds patterns in your own log (computed in code), tracks pain per body part, habits, shoe
  km and the countdown to your race.

**Try it:** https://coach.lasiichuk.com. Sign in with any Google account; as a guest you add
your own [OpenRouter key](https://openrouter.ai/settings/keys) (the AI runs on it, about
$0.005–0.02 a message) and can pick sample watch data if you don't use intervals.icu.

**Flow:** sign in with Google → a 5-step setup (connect intervals.icu · about you · goals ·
your files · a few questions) → **Today** (chat with quick log, the day card with "Why?", the
session with "Send to watch", habits, fuel). The interface is in English or Ukrainian.

UCU NLP course, Assignment 1. **Report: [`docs/report/README.md`](docs/report/README.md)**
(phase files in [`docs/report/`](docs/report/)), the plans in
[`docs/plans/`](docs/plans/), and the agent setup in [`AGENTS.md`](AGENTS.md) and
[`.claude/skills/`](.claude/skills/).

## How it works

The coach is an **agent**: each message (text, voice or photo) goes to one tool-using model
loop (Gemini 3.8 Flash; "Think harder" = Claude Sonnet 5.5). It acts for you, and every action
appears under the reply with **Undo**. Only sending a workout to the watch needs your OK.

```
message / voice / photo ─┬─ C7 safety gate (parallel)
                         └─ Coach agent (≤ 6 tool steps)
                              log_entries → C2 extractor → C3 nutrition (meals and drinks)
                              save_item / end_item → knowledge items (goals, races, gear, health…)
                              set_reminder → push notifications · update_profile
                              set_planned_workouts ← plan screenshot (vision) or chat
                              assess_day → C5 · plan_sessions → C6 + validator → card → Send to watch
                              nutrition_summary · health_summary · search_memory → C4 files
```

| | Component | Model |
|---|---|---|
| C0 | Setup interviewer (step 5 of the first-run window) | Gemini 3.8 Flash |
| C1 | Tool routing (the coach's choice of tools) | Gemini 3.8 Flash |
| C2 | Log extractor (events, dates) | Gemini 3.1 Flash-Lite |
| C3 | Nutrition: energy, macros, sugar, fibre, salt, caffeine, alcohol, iron, calcium, potassium, magnesium, vitamins C and D | Gemini 3.1 Flash-Lite |
| C4 | Sources: facts from your files + search (pgvector) | Flash-Lite + gemini-embedding-2 |
| C5 | Day type | Gemini 3.8 Flash |
| C6 | Workout planner + code validator | Gemini 3.8 Flash |
| C7 | Safety gate | Gemini 3.1 Flash-Lite |
| C8 | The coach's answers | Gemini 3.8 Flash |

**Pages** (each kind of item has one home where you edit it):

| Page | What it shows |
|---|---|
| Today | Chat with quick log (water, coffee, tea, beer) and a focus menu (Auto, Training, Nutrition, Health, Think harder); side panel: day type with reasons, labelled watch numbers, race countdown, session with fuel advice, habits, fuel, insight |
| Training | The week: your plan, coach suggestions, done; goals, races and gear (editable, shoe km) |
| Nutrition | Energy and macros against targets, what stands out, nutrients (vitamins folded), foods you eat most; fix any meal (×½, ×2, kcal, text) |
| Health | A year of HRV, resting HR, sleep, weight (with goal), fitness and fatigue, each explained; pain trend; patterns from your log; conditions, medication and lab results (editable) |
| Journal | The week in numbers vs last week; calendar; each day can be assessed, corrected and added to |
| Memory | Instructions to the coach, food and training preferences, life notes, your files and the review inbox |
| Settings | You, time zone, city (weather), language, your plan, all reminders, intervals.icu; Advanced: models, own key, cost |

Light and dark themes.

**Reminders:** morning, meal, evening and medication reminders arrive as web push notifications
(morning and evening ones have one-tap answers). A Cloud Scheduler job runs every 15 minutes: it
syncs intervals.icu hourly, sends reminders, a Sunday week summary and a nightly insight.

## Use it

The app is deployed at **https://coach.lasiichuk.com**.

1. Sign in with any Google account.
2. Setup step 1: paste your own [OpenRouter key](https://openrouter.ai/settings/keys) (the AI
   runs on it, about $0.005–0.02 a message), then connect intervals.icu, or press
   **Use sample watch data** if you don't have Garmin or intervals.icu.
3. Steps 2 to 5: about you, goals, optional files (e.g. a ChatGPT export), a few questions.
4. Today: tell the coach about your day, e.g.
   `Вчора 2 пива, спав 5 годин, зранку важка голова. На сьогодні 6 по 800. Що робити?`

## Run locally (development)

Requirements: [uv](https://docs.astral.sh/uv/), Postgres with pgvector (Neon or your own), an
OpenRouter key, a Firebase project with Google sign-in, and optionally a Langfuse project
(tracing is off without its keys). Account setup step by step: [`docs/setup.md`](docs/setup.md).

```bash
cp -n .env.example .env
```

Fill in `.env` (`-n` keeps an existing one), then:

```bash
uv sync
```

```bash
uv run python -m app.migrate
```

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. People in `ALLOWED_EMAILS` use the app's OpenRouter key; with
`OPEN_SIGNUP=true` anyone else can sign in and adds their own key.

## Tests and evals

```bash
uv run pytest
```

Tests use the database in `DATABASE_URL` (use a dev branch, never production) and create and
delete their own users under `@test.invalid`.

The tests check that every route needs sign-in, that one user can never read or change
another's data, the allowlist, the Origin (CSRF) check, encryption, the budget cap, the
intervals.icu client, the workout validator, patterns, meal edits, the language switch and the
agent's limits against prompt injection.

```bash
uv run python -m evals.run_all
```

This runs every component eval and prints a summary. Results go to `evals/results/`; the
discussion is in [`docs/report/05-evaluation.md`](docs/report/05-evaluation.md).

```bash
uv run python -m evals.run_e2e
```

The end-to-end check: 12 real chat turns on a synthetic athlete, verified in the database (needs
`ENV=dev`; it seeds the athlete itself).

```bash
uv run python -m evals.stats
```

95% intervals for the rate metrics and the majority-class baseline for the day type.

## Deploy

```bash
./scripts/migrate-prod
```

```bash
./scripts/deploy
```

`scripts/gc` keeps this project's gcloud config apart from any other (work) account. Production
secrets live in Google Secret Manager (`scripts/set-secret NAME`).

## Data and licences

- No personal data is in this repository. The eval sets in `evals/data/` are hand-written
  synthetic cases.
- `evals/data/c4_export.md` is a synthetic ChatGPT-style export with 24 planted facts
  (`evals/make_c4_export.py`).
- `evals/data/c3_nutrition.jsonl` contains 50 meals from **NutriBench v2**
  (dongx1997/NutriBench, CC BY-NC-SA 4.0), used for non-commercial evaluation, plus 10 Ukrainian
  meals with reference values from standard food tables.
