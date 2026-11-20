# Plan 10 — v7: family-ready app (part A of "life OS")

CRISP-DM phases: 1. Business understanding (new users), 4. Modeling (C9), 5. Evaluation,
6. Deployment. Part B (money, calendar, location, labs) is planned for later in
[plan 11](11-life-data.md).

## Goal

Two things, in this order:

1. **Make the app work for my father, brother and a few friends.** Today it is built for one
   expert user: setup requires an intervals.icu key, the sign-in page is English only, chat
   breaks when you leave the page, pages load slowly, photos need a confirmation. Fix that first,
   because nobody new will stay otherwise.
2. **Connect the rest of life** to the coach: money (Monobank, receipts), calendar, location and
   weather, lab results. Each one feeds the same coach and the same day view, so it can say
   things like "you spent 2× more on delivery this month". This part is in
   [plan 11](11-life-data.md); this plan is part 1 only.

## Scope

- **In (part A, family-ready):** chat that survives navigation; fast pages; photo meals logged
  without "Right?"; full EN/UA on every page, including sign-in; one-screen sign-up with "what do
  you want to track"; setup cards with step-by-step key instructions after sign-up; the app's
  OpenRouter key for everyone with a per-person cap, an admin page and a notification on each
  new sign-up; a Garmin-style daily nutrition review with ← date →.
- **Out:** everything in [plan 11](11-life-data.md) (location, calendar, labs, money, Garmin API).

## Why it breaks today (findings from the code)

| Problem | Cause in code | Fix |
|---|---|---|
| Chat breaks when you open another page | `POST /chat` is `async def` but calls the agent synchronously (`app/routes/pages.py:118`). For 5–30 s the whole server process is blocked, so the next page waits or times out. Same in `/transcribe`, file upload, tidy | Run the turn in a worker thread; save "turn in progress" in the DB; any page shows "Coach is replying…" and picks up the answer |
| Pages load slowly | Cloud Run `--min-instances 0` (cold start, several s); Neon scales to zero (≈1 s wake); Today calls intervals.icu live (`intervals.day_snapshot`), Open-Meteo, and may run the hourly year sync inside the page request; ~15 separate DB checkouts per page | Measure, then: render from our own DB tables only, load side cards after the page (`hx-trigger="load"`), move syncs to the 15-min cron tick, one DB connection per request, keep one warm instance |
| Photo needs "Right?" | Rule in `app/prompts/coach.md:10` | Log right away, show what was logged with Edit and Undo (already exist) |
| Sign-up is hard | Setup step 1 requires an intervals.icu key; 5 steps | One screen; every connection optional |
| Mixed language | `login.html` has no translations; Python error strings are English only | Translate everything; check by a script |

## Design

### A1. Chat that survives navigation

- New table `chat_turns (id, user_id, message_id, status running|done|failed, reply_id,
  error, started_at)`.
- `POST /chat` saves the message and the turn, starts `agent.run` in a thread pool, and returns
  the user bubble + a "Coach is replying…" bubble that polls `GET /chat/turns/{id}` every 1.5 s.
- `GET /` (and the rail on other pages) shows a running turn the same way, so going to Nutrition
  and back shows the reply when it is ready. A turn older than 3 min is marked failed with
  "Try again".
- All handlers that call the LLM become plain `def` (FastAPI runs them in a thread) so nothing
  blocks the server.
- Cloud Run: `--no-cpu-throttling`, so a turn keeps running after the browser leaves.
- Alternative: streaming (SSE). Lost: does not survive leaving the page, more code.

### A2. Speed

1. Add a `Server-Timing` header (DB, external API, render) and a cold/warm table in the report
   first, so the fix is measured, not guessed.
2. Today reads wellness and activities from `wellness_daily`/`activities` (already synced
   hourly) instead of calling intervals.icu on each page load. Live call only on "Refresh".
3. Syncs (intervals, weather, calendar, bank) run in `/cron/tick`, never inside a page request.
4. Side cards (rail, charts) load after the main page with `hx-trigger="load"`.
5. One DB connection per request (a request-scoped connection instead of ~15 checkouts); pool
   `min_size=1`.
6. `--min-instances 1` (≈ a few $/month). Neon free plan still sleeps after 5 min; accept ≈1 s on
   the first request after a pause, or pay for always-on (question 6).
- Target: warm Today < 600 ms server time, cold first load < 3 s.

### A3. Photo meals without confirmation

- Prompt change: a food photo → `log_entries` at once with realistic grams; the reply lists what
  was logged ("Logged: rice ~150 g, chicken ~120 g. Wrong? Tell me or tap Edit"). The action row
  already has Undo; the log sheet already allows editing.
- The unrealistic-amount guard stays.
- Eval: C1/agent e2e cases for photos change from "asks to confirm" to "logs + lists"; add 5
  photo cases (synthetic, public-licence food photos) to the vision set.

### A4. Full EN/UA everywhere

- Logged-out pages (sign-in) read the language from a `lang` cookie, default from the browser's
  `Accept-Language` (uk → Ukrainian). A toggle "English / Українська" at the top of sign-in.
  After sign-up the choice is saved to `user_prefs.lang`.
- Every user-visible string in Python (errors, budget messages, push texts, toasts) goes
  through `i18n.t()`.
- `scripts/i18n_check.py`: collects all `_()` / `t()` keys and fails if any is missing in
  `app/i18n_uk.json`; also flags plain English text left in templates. Runs as a test.
- Coach replies already follow the user's language; the new C9 does too.

### A5. Simple sign-up (mom test)

Flow for a new person:

```
Sign in (Google, big button, language toggle)
  → One screen "About you": name · language · main sport (or "none") · main goal (one line)
    · "What do you want to track?" (checkboxes with icons):
      Food & water (always on) · Training from my watch · Weather for my city · Reminders
  → Today (chat ready, works with no connections)
```

- No key is asked on that screen. intervals.icu stops being required: without it the coach
  works from chat logs only (plan 09, item 3). Training-related cards say "Connect your watch to
  see this".
- For each checked item, a **setup card** appears at the top of Today, one at a time, never a
  pop-up that blocks the screen: "Connect your Garmin (3 min)" → opens a sheet with numbered
  steps, a screenshot per step, a paste field, and a "Check" button that tests the key and
  says plainly what is wrong. "Later" hides it for 3 days. The same sheets live in
  Settings → Connections.
- Instructions written for a non-technical reader, in both languages:
  - Garmin via intervals.icu: create account → connect Garmin → Settings → Developer → copy key.
  - Weather: type your city.
  - Reminders: one "Allow notifications" button with the reason.
  - (Calendar, Monobank and location instructions come with plan 11.)
- The old 5-step wizard and the C0 question round become optional ("Tell the coach more" card).
- Check: a test account created from zero, 375 px, UA, without help, in < 2 min to the first
  logged meal. Also Oleksii's father as a real "mom test" (not a person's data in git).

### A6. One OpenRouter key for family, caps, admin

- `users` gets `ai_access` (`pending | allowed | blocked`) and `monthly_cap_usd`.
- With open sign-up, a new person gets `allowed` with a small starter cap (e.g. $1) so it works
  at once; the admin raises it (question 4).
- On each sign-up: web push to the admin's devices ("New sign-up: name, email") and a row on a
  new **/admin** page (admins only, from `ADMIN_EMAILS`): list of users, this month's cost,
  cap field, allow/block, which app key they use.
- "Dev and prod tokens": two app keys in Secret Manager (`OPENROUTER_API_KEY`,
  `OPENROUTER_API_KEY_FAMILY`); each user row says which one, so spending is split on the
  OpenRouter dashboard. A user's own key still wins over both.
- The per-user cap is enforced in `llm.check_budget` (already exists, now per user instead of
  the `MONTHLY_CAP_USD` constant).
- Alternative: one OpenRouter key per user via OpenRouter's key API with its own limit. Lost:
  more moving parts; our own cap already works.

### A7. Daily nutrition review

- `/nutrition` opens on a day: `‹  Today, Fri 20 Nov  ›`, swipe or arrows; `?day=YYYY-MM-DD`;
  no "›" past today. The 7/30-day views stay as a second tab ("Trends").
- The day page shows, top to bottom:
  1. Energy ring: eaten vs target for that day's type, with burned from training.
  2. Macros bars: protein, carbs, fat, fibre vs targets (targets from `nutrition_stats.targets`
     with that day's day type).
  3. Meals by time (breakfast / lunch / dinner / snacks, from log time): each with items, grams,
     kcal, macros, photo thumbnail; tap → existing edit sheet.
  4. Drinks: water, caffeine, alcohol.
  5. Micronutrients we track (iron, calcium, vitamin D, sodium, sugar…) vs references; if lab
     results exist (plan 11), low markers will be highlighted.
  6. Timing vs training: carbs before/after the day's session.
  7. **Coach's review**: 3 short lines (what went well, what was short, one tip for tomorrow).
     LLM call on the numbers above, cached per day, regenerated when that day's logs change.
     Language = UI language.
- New component **C9 Day review** (purpose: explain a day's nutrition; input: day totals,
  targets, meals, session; output: `{good, short, tip}` Pydantic model).

## Steps

1. Measure load time (Server-Timing, cold/warm table) → verify: numbers in
   `docs/report/` before any change.
2. A1 chat turns in background + non-blocking handlers → verify: test that a second request is
   served while a turn runs; browser: send, go to Nutrition, back → reply shows.
3. A2 speed changes → verify: same table after; targets met.
4. A3 photo logging → verify: e2e eval updated and re-run; one real photo on the demo account.
5. A4 i18n (cookie, toggle, Python strings, check script) → verify: `i18n_check` passes;
   `/ui-check` on sign-in and every page in UA.
6. A6 access, caps, admin page, sign-up push → verify: two-user tests (non-admin gets 404 on
   /admin), cap blocks at the limit, push arrives on a test sign-up.
7. A5 sign-up + setup cards + instructions + no-intervals mode → verify: new test account from
   zero at 375 px in UA; every page works without intervals.icu.
8. A7 nutrition day view + C9 → verify: `/ui-check`; `evals/run_c9.py`.
9. Deploy part A; invite father/brother.

## Evaluation

| Component | Metric | Data | Good |
|---|---|---|---|
| Chat turns (A1) | turn survives navigation; no blocked requests | test + browser | 100% |
| Speed (A2) | server time p50 warm/cold for Today, Nutrition | Server-Timing, 20 loads | < 600 ms / < 3 s |
| Photo logging (A3) | items F1, grams within 30% | 20 meal photos (vision set from plan 09) | F1 ≥ 0.8 |
| i18n (A4) | missing translations | check script | 0 |
| Sign-up (A5) | time to first logged meal, steps | 3 people, test account | < 2 min |
| C9 Day review | grounded (no number not in input), useful (judge 1–5) | 15 synthetic days | 100% grounded, ≥ 4 |

All eval sets synthetic, no personal data in git. Each gets `evals/run_cNN.py` and a row in the
report, run with `/eval`.

## Decisions taken (defaults; the questions were not answered before building)

1. Garmin stays behind intervals.icu (its setup gets step-by-step help). Official Garmin API →
   plan 11.
2. Sign-in stays Google only (one big button).
3. "Dev / prod token" read as: two app keys, a `main` and an optional `family` key
   (`OPENROUTER_API_KEY_FAMILY`), chosen per person on /admin, so spending is split on the
   OpenRouter dashboard.
4. New sign-ups are allowed at once with a $1 starter cap; the admin gets a web push and
   raises the cap on /admin. Members from `ALLOWED_EMAILS` keep the $20 cap.
5. Hosting must stay free (Oleksii, after review): scale to zero, request-based CPU; replies
   keep CPU through a self-request (see Result).
6. The "what do you want to track" list shows only what works today (food, training from the
   watch, weather for a city, reminders). Calendar, money and lab tests are added in plan 11.

## Acceptance criteria

- [x] Sending a message and opening another page never loses or blocks the reply.
- [x] Today and Nutrition load under the A2 targets (measured locally, recorded; not yet in prod).
- [x] A meal photo is logged without a question; Edit and Undo work; a correction replaces it.
- [x] Every page, including sign-in and error messages, is fully EN and UA; check script = 0.
- [x] A new person signs up on a phone in UA, chooses what to track, and reaches Today without
      any key; setup cards explain each key step by step (checked on a test account, not yet
      with a real non-technical person).
- [x] New sign-ups notify the admin; /admin sets caps; caps are enforced; tests cover /admin
      (404 for others) and the new endpoints.
- [x] Nutrition day view with ‹ date › and the coach's day review.
- [ ] `/ui-check` at 375/1280, light/dark, EN/UA for every changed page: done for sign-in,
      welcome, Today, the watch sheet and Nutrition in the combinations listed in Result;
      /admin was checked by tests only.

## Result (2026-11-20)

**Built (part A, all seven items):**

- A1 chat turns: `chat_turns` table (migration 006), `POST /chat` starts the agent in a thread
  pool and returns a polling bubble; `GET /chat/turns/{id}`; Today shows a running turn after
  you come back; a second message waits for the first; 3-minute timeout. `/transcribe` no
  longer blocks the server, and file uploads run in a thread.
- A2 speed: `Server-Timing` header; autocommit pool; the liveness check only after 20 s idle;
  side panel loaded after the page (`GET /rail`); watch numbers from the synced table; syncs in
  a background thread instead of inside page requests (Health and Training used to run a full
  sync inline every day until today's wellness arrived).
- A3 photos: prompt + `log_entries(replaces_last)`.
- A4 i18n: sign-in toggle (`POST /lang`, kept in the session, saved to the account),
  `Accept-Language` default, translated errors / pushes / action lines, units, and
  `scripts/i18n_check.py` as a test. 151 new Ukrainian strings, formal "ви" like the rest.
- A5 sign-up: one screen (`/welcome`), `users.tracks`, setup cards (watch with a 5-step sheet,
  height and weight, city, reminders, C0 questions) one at a time with Later; intervals.icu
  optional everywhere.
- A6 access: `ai_access`, `monthly_cap_usd`, `key_pool` on users; $1 starter cap, $20 for
  the invite list; optional `OPENROUTER_API_KEY_FAMILY`; `/admin`; web push to admins on each
  new sign-up.
- A7 nutrition: day view with ‹ date › and swipe, meals by breakfast/lunch/dinner/snacks,
  drinks and training, nutrients; C9 day review (`app/pipeline/day_review.py`,
  `app/prompts/c9_day_review.md`, cache table `day_reviews`, migration 007).

**Verified:**

- `uv run pytest`: 59 passed (12 new in `tests/test_v7.py`), ruff clean, `i18n_check` 0 missing.
- `evals/run_e2e.py`: 14/14 (two new photo cases).
- `evals/run_c9.py`: grounded 1.00, language 1.00, main point 0.93 (14/15), no false claim 1.00,
  usefulness 3.6/5 (target 4.0 not met; see report 05).
- Speed (local, laptop → Neon Frankfurt): Today 2.4–2.6 s → 0.18–0.29 s; Health 2.4 s →
  0.82 s; Training 2.6–2.8 s → 0.64 s; Nutrition about 2 s → 0.5–0.7 s.
- Browser checks: the chat survives Today → Nutrition → Today (UA, 375 px, dark); welcome
  screen (375 px, UA and EN, light); setup card and watch sheet (375 px, light); Nutrition day
  (1280 px light EN, 375 px dark UA, no horizontal scroll); sign-in toggle (375 px, dark).

**Deviations:**

- The watch sheet has numbered text steps, no screenshots (I have no intervals.icu account
  to take them from).
- "Timing vs training" on the day page shows the day's training but not carbs before/after
  it: synced activities have no start time. C9 flags a missing breakfast on hard days instead.
- The "what to track" list shows only what works now (training, weather, reminders); calendar,
  money and labs come with plan 11.
- Hosting stays free: scale to zero, request-based CPU, max one instance. A reply keeps CPU
  through an open request from the instance to itself (`/cron/hold/{id}`) instead of the
  planned `--min-instances 1` / `--no-cpu-throttling`.

**Not verified:**

- Nothing is deployed. Migrations 006 and 007 are on the dev branch only.
- A real web push to the admin's phone on sign-up (the call is tested with a stub).
- A real non-technical person going through sign-up and the intervals.icu steps.
- Production page speed and the background turn under Cloud Run CPU throttling.
- /admin visually; the whole app in every light/dark × EN/UA × width combination.
