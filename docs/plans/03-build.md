# Plan 03 — Build everything for the submission

CRISP-DM phase: 4. Modeling, 5. Evaluation, 6. Deployment.
Status: draft, waiting on "go". This plan supersedes the Steps section of `02-submission.md`;
its decisions table still holds. Security rules: `docs/design-guidelines.md` (S1–S13, U1–U12).
Deadline: 2026-11-15, evening.

## Goal

Build the whole submission in one pass:
- a hosted app that you and Ivan sign in to with Google;
- intervals.icu connected (read, plus write after **Apply**);
- one chat that logs the day in Ukrainian or English, decides the day type and proposes an
  adapted workout that goes to the Garmin watch;
- an eval script and a recorded result for every NLP component.

## Scope

- In: migrations, sign-in, intervals.icu connect and sync, the chat pipeline C0–C8, Today /
  About me / Settings screens, the eval sets and scripts, Cloud Run + Firebase Hosting, README,
  report.
- Out (after the submission): ChatGPT import and the full wiki, web push and reminders, gear
  mileage, encrypting all text at rest, streaming replies, the custom domain (last, when Ivan
  adds the A record).

## Facts checked against the real API (2026-11-14, your account)

- **Athlete** (`GET /athlete/{id}`) has `sex`, `icu_date_of_birth`, `height`, `weight` /
  `icu_weight`, `icu_resting_hr` and `timezone` (`Europe/Kiev`).
  - `sportSettings[]` has one entry per sport group: Ride*, Run*, Swim*, Other. Each has
    `types`, `lthr`, `max_hr`, `hr_zones`, `threshold_pace` (m/s), `pace_units` and `ftp`.
  - `shoes` and `bikes` are empty, so gear comes from the interview.
- **Wellness** (`GET /athlete/{id}/wellness?oldest&newest`) has `hrv`, `restingHR`, `sleepSecs`,
  `sleepScore`, `sleepQuality`, `ctl`, `atl`, `rampRate`, `steps` and `vo2max`.
- **Activities** (`GET /athlete/{id}/activities?oldest&newest`): your types are Run, Swim and
  WeightTraining; Ivan's will include Ride. They have `type`, `distance`, `moving_time`,
  `icu_training_load`, `average_heartrate`, `feel` and more.
- **Events**: 0 in ±60 days. **Garmin Coach workouts do not reach intervals.icu.** So the coach
  learns the Garmin Coach workout from you ("Garmin wants 8×400 today"). C2 extracts it as a
  `planned_workout` log, and C6 keeps, modifies, replaces or adds to it.
- Garmin upload of planned workouts is on (`icu_garmin_upload_workouts = true`), so an event we
  create goes to the watch.

## Design

### Request path and modules

```
Browser ─► Firebase Hosting (*.web.app, later coach.lasiichuk.com) ─► Cloud Run "coach" (FastAPI)
                                                     ├─ Neon Postgres (prod: production, dev: main)
                                                     ├─ intervals.icu (per-user key, encrypted)
                                                     ├─ OpenRouter (app/llm.py) ─► Langfuse traces
```

```
app/
  config.py db.py llm.py           done
  migrate.py                       applies migrations/*.sql in order, records schema_migrations
  auth.py                          token check, allowlist, session, current_user, Origin check
  crypto.py                        Fernet encrypt/decrypt + last4
  intervals.py                     client: athlete, wellness, activities, events, create/delete
  store.py                         every DB read/write; every function takes user_id first
  pipeline/                        one file per component (table below) + validator.py, turn.py
  prompts/                         one .md per LLM component (the one visible place)
  routes/                          pages.py auth.py chat.py proposals.py me.py settings.py
  templates/ static/               Jinja + HTMX, tokens.css, Firebase JS (pinned CDN version)
migrations/001_init.sql
evals/data/*.jsonl  evals/run_<component>.py  evals/run_all.py  evals/results/
tests/
Dockerfile  scripts/deploy
```

### Data model (`001_init.sql`)

Every personal table has `user_id uuid not null references users on delete cascade`.
All times are `timestamptz` in UTC; days are `date` in the user's time zone.

| Table | Columns |
|---|---|
| `users` | id, firebase_uid (unique), email (unique), display_name, time_zone, created_at |
| `user_secrets` | user_id, provider, ciphertext, last4, external_id (athlete ID), created_at; PK (user_id, provider) |
| `profile_fields` | user_id, key, value jsonb, source (`intervals` / `user` / `ai`), updated_at; PK (user_id, key) |
| `facts` | id, user_id, category (health, injury, medication, goal, race, gear, preference, life), text, status (active / resolved), valid_from, valid_to, source, message_id, created_at |
| `logs` | id, user_id, kind (meal, drink, alcohol, sleep, mood, pain, symptom, medication, activity, planned_workout, note), day, occurred_at, data jsonb, message_id, created_at |
| `chat_messages` | id, user_id, role, content, trace_id, created_at |
| `day_assessments` | user_id, day, day_type, confidence, reasons jsonb, inputs jsonb, trace_id, created_at; PK (user_id, day) |
| `proposals` | id, user_id, day, status (proposed / applied / undone / dismissed), workout jsonb, rationale, evidence jsonb, intervals_event_id, created_at, applied_at |
| `llm_usage` | id, user_id, component, model, input_tokens, output_tokens, cost_usd, created_at |
| `audit_log` | id, user_id, actor (user / ai / system), action, entity, entity_id, before jsonb, after jsonb, created_at |

Why the profile is key/value: you asked for the interviewer to decide which fields matter, so a
fixed column list would be wrong. The keys C0 tracks are listed in `pipeline/interview.py`.

### Sign-in and sessions

1. `/login` loads Firebase JS (pinned version) and shows **Continue with Google** (popup).
2. The browser POSTs the ID token to `/auth/session`. The server checks it with
   `google.oauth2.id_token.verify_firebase_token(audience="daily-coach-af64d")`, then requires
   `email_verified` and an email on `ALLOWED_EMAILS`. A refused email gets a "This app is
   private" page and no DB row.
3. The server upserts `users`. Starlette `SessionMiddleware` sets the `__session` cookie
   (`HttpOnly`, `SameSite=Lax`, `Secure` in prod, 14 days), holding only `user_id`.
   - Its signing key is derived from `APP_ENCRYPTION_KEY` (HMAC with the label "session"), so
     no new secret is needed.
4. `current_user` is a FastAPI dependency on every router. The only public paths are
   `/login`, `/auth/session`, `/health` and `/static`. A request without a session is
   redirected to `/login`, or gets 401 for HTMX requests.
5. A middleware rejects any POST whose `Origin` is not `APP_ORIGIN` (CSRF guard).
   `/auth/logout` is a POST.

### intervals.icu connect and sync

- **Settings → Connect:**
  1. You enter the API key and athlete ID.
  2. The app makes a test `GET /athlete/{id}`.
  3. On success it encrypts and stores the key (only `last4` is ever shown), and fills
     `profile_fields` from the athlete: sex, birth year, height, weight, time zone, resting HR,
     sports, and per sport LTHR, max HR, HR zones, threshold pace and FTP. Each field gets
     `source=intervals`.
- **Client:** httpx with a 15 s timeout and 2 retries on 429/5xx. Errors become plain
  messages: 401/403 → "Key or athlete ID is wrong", timeout → "intervals.icu is not
  responding, try again". The key never appears in logs or prompts.
- **Today's data:** wellness for the last 8 days and activities for the last 14 days, fetched
  when needed and cached in memory per user for 5 minutes. Baselines (7-day HRV mean, resting
  HR mean, sleep mean) are computed in code, not by the LLM.
- **Write:** `POST /athlete/{id}/events` (category WORKOUT, type, `start_date_local`, name,
  description in intervals.icu workout text). **Undo** = `DELETE` of that event.
  - Before relying on it, step 4 tests the round trip: create an event on a date 30 days ahead,
    read it back to see the parsed steps, delete it. The real responses are saved as test
    fixtures with secrets removed.

### One chat turn (one Langfuse trace `handle-chat-turn`, session = user + day)

```
message ─┬─► C7 safety ──┐   (C7 and C1 run in parallel)
         └─► C1 router ──┤
                         ├─ log         ─► C2 extract ─► meals ─► C3 nutrition ─► logs, facts
                         ├─ profile     ─► C0 interview (extract answers, choose next question)
                         ├─ plan / or a log that changes today (alcohol, sleep, pain, symptom,
                         │   planned_workout) ─► C5 day type ─► C6 planner ─► validator ─► proposal card
                         └─ always      ─► C8 reply (short answer from context + what was done)
red flag (C7) ─► reply with "see a doctor" + no workout proposal; logs are still saved
```

| # | Component | Input → output | Model |
|---|---|---|---|
| C7 | Safety gate | message → `{red_flag, reason}` (chest pain, fainting, fever while training, …) | Flash-Lite |
| C1 | Router | message + last 4 messages → intents ⊆ {log, question, plan, profile, chitchat} | Flash-Lite |
| C2 | Log extractor | message + now (user tz) → events[] {kind, day, time, data} + facts[]; resolves "вчора ввечері" etc. | Flash-Lite |
| C3 | Nutrition | meal text → items[] {name, grams}, kcal, carbs, protein, fat | Flash-Lite |
| C0 | Interviewer | known profile + facts + slot list → filled slots + ≤2 next questions | Flash |
| C5 | Day type | wellness vs baselines, load (ctl/atl), today's logs, active facts → recover/easy/normal/push, confidence, reasons with evidence refs | Flash |
| C6 | Planner | day type, Garmin Coach workout (if told), 14-day activities, goals, zones, preferences → workout {sport, name, steps[], minutes, rationale} | Flash |
| — | Validator (code) | workout → ok / violations[] | — |
| C8 | Reply | intents, results of the steps above, profile/facts/logs context → short reply, says what is missing | Flash-Lite |

- **Outputs:** every component returns a Pydantic model (`complete(schema=...)`), with one
  retry if the JSON doesn't match. Each call records `llm_usage` and is checked against a $5
  per-user monthly safety cap.
- **Validator rules:**
  - the sport is one of the user's sports (from intervals.icu types or the profile);
  - the steps parse;
  - total time is 10–180 min;
  - recover: ≤ 40 min, Z1–Z2 only; easy: ≤ 75 min, nothing above Z2;
  - an active injury or illness fact means nothing above Z2;
  - a red flag means no workout at all.
- **Validator retry:** on a violation, C6 gets one retry with the violation list; if it still
  fails, the user sees no card and the reply says why.
- **Rendering:** the validated steps become intervals.icu workout text, e.g.
  `- 10m Z2 HR`, `5x`, `- 400m 95-100% Pace`. You see a before → after card; **Apply** writes
  it to intervals.icu, and **Undo** deletes it.
- **Onboarding:** the first visit to Today starts C0. Prefilled fields are shown as known; it
  asks only about what's missing (goals and races, sports and preferences, weekly availability,
  injuries and health, medications, sleep target, gear). Every question can be skipped.
  Today shows "Profile 60% · continue".

### Screens (design system: `docs/design-guidelines.md` Part B)

- **Sign in.**
- **Today:**
  - day type card (big label plus evidence chips);
  - Garmin Coach / proposed workout card (Apply / Undo);
  - today's logs, with kcal total;
  - chat with 3 context chips.
- **About me:** profile fields with source badges, editable; facts by category (edit, resolve,
  delete); every edit goes into `audit_log`.
- **Settings:** intervals.icu (connected, key ••••1a2b, test, disconnect), AI cost this month,
  sign out.

Phone: bottom bar. Desktop: left rail, with About me as a side panel. Every screen has loading,
empty, error and success states.

### Deploy

- **Image:** `Dockerfile` (python:3.12-slim + uv).
- **Deploy script:** `scripts/deploy` checks that the project is `daily-coach-af64d` through
  `./scripts/gc`, then runs:
  - `run deploy coach --region europe-west1 --min-instances 0 --max-instances 2`, with the
    secrets passed as env (`--set-secrets`) and the plain values set via `--set-env-vars`;
  - `firebase deploy --only hosting --project daily-coach-af64d`.
- **Access:** the Cloud Run service account gets `secretAccessor` on the 4 secrets.
- **Prod migrations:** run from your Mac with the URL read from Secret Manager into the
  command's environment, never printed. `migrate.py` switches to the direct (non-pooler) host.

## Steps (time boxes are targets)

Tonight:
1. **Migrations** (30 min)
   → verify: `uv run python -m app.migrate` twice; the second run applies nothing; `\dt`
   shows the tables on Neon `main`.
2. **Auth + crypto + `current_user` + Origin check** (1.5 h)
   → verify: `test_routes_protected` (walks every route), allowlist test, bad-Origin test,
   crypto round-trip; you log in on localhost once.
3. **Layout, design tokens, the 3 screens with empty states** (1.5 h)
   → verify: screenshots at 375 and 1280 px, light and dark.
4. **intervals.icu client, Settings connect, prefill, write round trip on a future date**
   (1.5 h)
   → verify: your name shows after connect; profile fields match intervals.icu; an event
   appears and is deleted; the key is not in logs or HTML; fixture tests pass.
5. **`store.py` + the two-user isolation test** (45 min)
   → verify: user B gets 404 on every one of user A's ids.

Sunday morning:
6. **C7, C1, C2, C3 + prompts + chat endpoint + logs on Today** (2.5 h)
   → verify: "вчора випив 4 пива, спав 5 год, коліно болить" gives logs dated yesterday and
   today plus a knee fact; the Langfuse trace has one generation per component.
7. **C5, C6, validator, proposal card, Apply / Undo** (2.5 h)
   → verify: the sentence above gives a recover day and a Z1–Z2 proposal; Apply puts it on the
   intervals.icu calendar (and the watch after sync); Undo removes it.
8. **C0 interview + C8 reply** (1 h)
   → verify: a fresh user (Ivan's account or a second test email) gets asked only about
   missing fields.

Sunday midday:
9. **Eval sets + scripts + results** (2.5 h; your label review ~30 min)
   → verify: `uv run python -m evals.run_all` prints the table, and it is written to
   `evals/results/` and `docs/report/05-evaluation.md`.

Sunday afternoon:
10. **Deploy** (1 h)
    → verify: login works at `https://daily-coach-af64d.web.app` from your phone on mobile
    data; a chat turn works in prod.
11. **README, report phases 2–6, demo script** (1.5 h)
    → verify: a clean clone + README runs locally. Then you record the ≤10 min video.
12. **Custom domain** (when Ivan is ready; 15 min of his time)
    → verify: HTTPS works on the subdomain, and it is added to Firebase authorized domains.

If time runs short, cut in this order: C0 → Undo → C8 polish → deploy (grading needs the local
run) → the Ukrainian meals in the C3 set.

## Evaluation

Each set is JSONL in `evals/data/`, with no personal data.
- **How the sets are made:** the SMART model drafts the cases from a list of situations (UA,
  EN, mixed), and you correct the labels.
- **How they run:** each script reports its metric plus a list of failures; eval traces are
  tagged `eval` in Langfuse.

| Comp. | Set | Metric | Good enough |
|---|---|---|---|
| C7 | 40 messages, half red flags | recall, false-alarm rate | recall 1.0, FAR ≤ 0.15 |
| C1 | 60 messages, multi-label | macro-F1, per-intent F1 | ≥ 0.85 |
| C2 | 50 messages with gold events | event-kind P/R/F1, day accuracy, field F1 | F1 ≥ 0.80, day ≥ 0.90 |
| C3 | 50 NutriBench meals + 15 Ukrainian meals | kcal MAE, carbs MAE; vs. a naive baseline (mean kcal) | beats baseline clearly |
| C5 | 30 day scenarios with your label | accuracy, Cohen's κ; vs. a code rule on HRV + sleep | κ above the rule |
| C6 | 20 scenarios | validator pass rate (first try / after retry), LLM-judge rubric 1–5, 5 judged by you too | 100% after retry, rubric ≥ 4 |
| C0 | 5 synthetic athletes with hidden profiles + simulated user | slot coverage, redundant questions | ≥ 0.9, 0 redundant |
| C8 | 15 questions with known answers in context | judge: grounded and correct, says when missing | ≥ 0.85 |
| App | tests | protected routes, isolation, allowlist, crypto, budget, validator | all pass |

## Assumptions / open questions

- **NutriBench:** public on Hugging Face. Step 9 checks its licence before use; if it doesn't
  allow use, C3 uses 50 hand-checked meals from USDA FoodData Central.
- **Second user for testing:** Ivan's Gmail must be on `ALLOWED_EMAILS` (or a second test Gmail
  of yours) for the isolation and onboarding checks.
- **Garmin Coach:** the workout comes from your words, since it isn't in intervals.icu. If you
  later want it read automatically, the Garmin Personal API (read-only) is the place to check,
  after the submission.

## Acceptance criteria

- [ ] You and Ivan can sign in; any other Google account sees "This app is private".
- [x] intervals.icu connects; the profile is prefilled; the key is stored encrypted and never shown.
- [x] A UA/EN message produces correctly dated logs, kcal for meals, and facts.
- [ ] A bad day leads to a recover/easy proposal with evidence; Apply puts it in intervals.icu
      (→ Garmin); Undo removes it.
- [x] A first visit gets an interview that asks only for missing information.
- [x] Every LLM call is traced in Langfuse with user, session, model and cost.
- [x] `evals.run_all` produces a result for every component, recorded in `docs/report/`.
- [x] Tests pass: protected routes, two-user isolation, allowlist, Origin, crypto, budget, validator.
- [ ] The app runs locally from the README and at `https://daily-coach-af64d.web.app`.

## Result (2026-11-14)

**Built:** everything in Scope except the custom domain, which waits for Ivan's DNS records. The
user also asked for voice input, and it was added: the browser's speech recognition with a UA/EN
switch; the recognised text goes into the input box.

**Verified:**
- `uv run pytest`: 21 tests pass (protected routes, two-user isolation, allowlist, unverified
  email, bad token, Origin, crypto, budget cap, intervals client with mocked HTTP, validator).
- Migrations applied twice on Neon `main` (the second run does nothing), and once on
  `production`.
- Real intervals.icu round trips: read athlete, wellness and activities; create a run and a swim
  workout 30 days ahead; read back the parsed steps; delete.
- An end-to-end chat turn with a temporary user: correct dates, 247 kcal meal, knee fact,
  Recover 0.95, rest proposal, Ukrainian reply, 17.8 s, $0.007; trace in Langfuse.
- UI screenshots at 375 px (light and dark) and 1280 px (light).
- Deployed to https://daily-coach-af64d.web.app: `/login` 200, `/` → 303 to login, a bad-Origin
  POST → 403.

**Evals** (details in `docs/report/05-evaluation.md`):

| Component | Result |
|---|---|
| C7 Safety | recall 1.0, false-alarm rate 0 |
| C1 Router | macro-F1 0.93 |
| C2 Extractor | (kind, day) F1 0.91 |
| C3 Nutrition | kcal MAE 69 (NutriBench) and 42 (UA) vs baselines 193 and 112 |
| C5 Day type | κ 0.91 vs 0.49 for the rule |
| C6 Planner | 100% valid after retry, judge 3.98 (v1 3.73) |
| C0 Interviewer | coverage 1.0, 0 redundant questions |
| C8 Reply | correct 0.93 |

**Deviations from the plan:**
- `/healthz` → `/health` (Cloud Run reserves paths ending in "z").
- `APP_ORIGIN` accepts several origins, and the Origin check now matches whole origins (the
  first version was a prefix match).
- HR zones are stored as explicit ranges after the C8 eval showed the model misreading
  intervals.icu's upper-limit list.
- The validator requires a main set (from the C6 eval).
- The eval cases were written by the coding assistant rather than drafted by Gemini, to avoid
  the model grading its own style.

**Not verified:**
- A real Google sign-in (yours and Ivan's), locally and on the live site.
- Voice input on a real phone.
- Apply on today's date (only tested on future dates, to keep your calendar clean).
- A full chat turn on the live site.
- Langfuse traces from production.
