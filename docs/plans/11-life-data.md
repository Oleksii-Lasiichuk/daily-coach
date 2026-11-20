# Plan 11 — Life data: location, calendar, labs, money

CRISP-DM phases: 1. Business understanding (what each source is for), 2. Data understanding
(the new sources and their limits), 3. Data preparation (synthetic eval sets), 4. Modeling
(C10 lab extraction, C11 spend category, two new code components), 5. Evaluation,
6. Deployment.
Status: **approved 2026‑11‑20** (Oleksii's answers to the open questions are in "Decisions"
at the end). Starts after [plan 10](10-v7-life-os.md) (family-ready app) is deployed. Nothing
here is built yet.

## Goal

Connect the rest of life to the coach, so it can reason across areas and say things like:

- "28 °C and dew point 20 °C at 18:00: run the tempo 2–3 % slower, or go at 07:00 when it is 19 °C."
- "You have meetings until 19:30 and an 07:00 flight tomorrow: do the 40-min easy run at 12:30,
  skip the gym, and be in bed by 22:30."
- "Ferritin was 18 µg/L in September (below your lab's range): iron-rich food on hard weeks
  matters, and ask your doctor about a re-test."
- "You spent 2× more on delivery this month than your usual, although your goal is to cook."

Four sources for everyone plus one personal one (B5), each its own shippable slice (code + migration + setup card + sync + eval +
report section + deploy):

| Slice | Source | New components | Size |
|---|---|---|---|
| B1 | Phone location + richer weather (Open-Meteo) | C12 Weather advice (code) | S–M, ~3 days |
| B2 | Calendar via an iCal (ICS) link | C13 Day windows (code), C6 gets windows | M, ~4 days |
| B3 | Lab results from a photo or PDF | C10 Lab extraction (LLM + code) | M, ~4 days |
| B4 | Money: Monobank API + receipt photos + insights | C11 Spend category (rules + LLM), receipt extraction | L, ~7 days |
| B5 | Garmin Personal API, Oleksii's own account only (read-only) | Garmin sync (code) | S–M, ~2 days |

"Days" are focused working days with Claude Code, including evals, `/ui-check` and the report.

**Order: B1 → B2 → B3 → B4, as planned.** Reasons: B1 is the smallest and extends code that
exists (`app/weather.py`, the planner already gets `weather`), with no secrets. B2 changes the
core loop (when training happens) and gives C6 a hard, checkable rule. B3 is one new LLM
component on health data, with a small UI. B4 is the largest and the most sensitive (a bank
token, a public webhook, money rows): it benefits most from the patterns the first three set
(secret storage, sync in the tick, setup sheets). Doing money first would mean building the
riskiest slice with the least reuse. If money matters more to you than calendar, B4 can move
before B2 — they don't depend on each other — but keep B1 first.

## Scope

- **In:** "Use my location" in the browser + hourly weather, air quality, UV, sunrise/sunset,
  heat/cold/dark/AQI rules; calendar through a secret/public iCal link; lab results from a photo
  or a text PDF, with trends; Monobank personal API (statement import + webhook); receipt photos;
  spending categories and insights; Garmin Personal API for Oleksii only (B5). Each with a setup card (EN and UA), a sync in `/cron/tick`
  where it needs one, an eval, two-user isolation tests and a report section. New "what to
  track" options on the welcome screen.
- **Out (and why):**
  - PrivatBank, dropped: there is no personal API for individuals (`api.privatbank.ua` offers
    only "Публічні" exchange rates and "API для юр.осіб", checked 2026‑11‑20), and no statement
    file upload either. Money = Monobank + receipt photos only.
  - Google Calendar OAuth / push (needs Google app verification for sensitive scopes); the ICS
    link covers Google, iCloud and Outlook read-only.
  - Background location, route suggestions, native app.
  - Writing anything to the calendar or the bank. Everything here is read-only.
  - Garmin for other people (see "Garmin" below): intervals.icu stays the bridge for everyone
    and the only way to send workouts to the watch. B5 adds the Personal API for Oleksii's own
    account only.

## Rules that apply to every slice

From `AGENTS.md` and `docs/design-guidelines.md`, repeated because each slice must pass them:

1. **Code for numbers, LLM for language** (like C9 `day_review.analyse` in
   `app/pipeline/day_review.py`): sums, ranges, unit conversions, time windows, thresholds and
   "is this out of range" are computed in code. An LLM only reads messy input (a lab sheet, a
   receipt, an unknown merchant name) into a Pydantic model, or puts computed facts into words.
2. **Every LLM call** goes through `app/llm.py` (`trace()` + `complete()`), prompt in
   `app/prompts/<id>.md`, output parsed into a Pydantic model, traced in Langfuse, counted
   against the person's AI cap.
3. **Syncs never run inside a page request.** They run in `push.tick()` (Cloud Scheduler calls
   `/cron/tick` every 15 minutes), each guarded by `store.mark_once` / a `next_at` column so a
   user is synced at most at the stated rate. A page may only start a background sync
   (`threading.Thread`, like `health.sync_soon`) after an explicit "Refresh" or right after setup.
4. **Every personal-data query has `user_id`**; every new endpoint gets a case in
   `tests/test_isolation.py` (user B cannot read, change or delete user A's rows).
5. **Secrets** (ICS URL, Monobank token, webhook token) are stored in `user_secrets` encrypted
   with `app/crypto.py` (Fernet), shown as "…last4", never logged, never sent to an LLM.
6. **Schema changes only by numbered migrations**: `008_…` to `011_…` below. Times in UTC
   (`timestamptz`), shown in the user's time zone.
7. **UI:** mobile-first, design system in `docs/design-guidelines.md`, all strings in
   `app/i18n_uk.json` (`scripts/i18n_check.py` stays at 0 missing), `/ui-check` at 375 and
   1280 px, light and dark, EN and UA, on the demo athlete.
8. **No personal data in git.** Eval sets are synthetic and generated by scripts in `evals/`.
9. **Free hosting.** No new paid API, no new always-on compute (see "Free hosting check").

## Garmin (decision: keep intervals.icu as the bridge)

What exists today, checked 2026‑11‑20 on
<https://developer.garmin.com/gc-developer-program/overview/>:

- **Garmin Connect Personal API** (new, self-serve): a person creates a personal API key in
  Garmin Connect Web (`connect.garmin.com/app/settings/personalApiToken`), choosing an expiry of
  30, 90, 180 days or 1 year; the key is exchanged for a 24-hour access token at
  `personal.connectapi.garmin.com/personalapitoken-service/…/token`; no refresh tokens.
  Activity (JSON, .FIT), Health (JSON) and Women's Health data, **pull only**. **No Training
  API**, so it cannot send workouts to the watch. The FAQ says it is "not intended for commercial
  applications serving multiple end users"
  (<https://developer.garmin.com/gc-developer-program/personal/personal-faq/>).
- **Business (Starter / Enterprise)**: apply through a Garmin form; Starter includes Activity,
  Health, Courses and **Training** APIs, push delivery only, no historical data, "limited" user
  capacity. The overview does not state cost, approval time or company requirements (the old
  program FAQ URL returns 404).
- **Unofficial libraries** (e.g. `garminconnect`, `garth`) log in with the user's Garmin
  password and keep session tokens on our server: against Garmin's terms, and a real risk with
  family accounts. Not used.

**Decision:** intervals.icu stays the bridge for everyone. It reads Garmin (wellness,
activities) and writes planned workouts to the watch, it is free, and family members set it up
once with the existing sheet. **Oleksii uses the Personal API for his own account only** (slice
B5): his own key, his own data, personal use — what the Personal API is for. It is not offered
to other users (that would be the "multiple end users" case the FAQ excludes). No Business
application now; it would need an app description, a privacy policy and terms, a demo and a
review wait, and is worth it only if the app ever outgrows family use.

## Free hosting check

| Item | Free limit (source) | This plan's use |
|---|---|---|
| Cloud Run (request-based billing, as deployed: `--cpu-throttling --min-instances 0 --max-instances 1`) | 2 M requests, 180 k vCPU‑s, 360 k GiB‑s per month (<https://cloud.google.com/free/docs/free-cloud-features>) | + Monobank webhook calls (a few per person per day), + longer tick. Far below the limit. **Do not switch to `--no-cpu-throttling`**: the free tier lists request-based numbers only (<https://cloud.google.com/run/docs/configuring/billing-settings>). |
| Cloud Scheduler | free jobs per billing account (<https://cloud.google.com/scheduler/pricing>) | No new job: everything rides the existing 15-min `/cron/tick`. |
| Secret Manager | 6 active versions, 10 k accesses / month | No new server secrets. User tokens live encrypted in Postgres. |
| Neon Free | 1 GB storage per project, 100 CU‑hours per project, scale to zero after 5 min (<https://neon.com/pricing>) | Rows are tiny (transactions ~200 B, ~1–2 k/year per person; lab rows ~50/year). Ticks every 15 min already wake the DB; no new wake-ups. **Watch CU‑hours** in the Neon console after B4. |
| Firebase Hosting Spark | 10 GB storage, 360 MB/day transfer (<https://firebase.google.com/pricing>) | No change (rewrites to Cloud Run). |
| Open-Meteo | free for non-commercial use: < 10 000 calls/day, 5 000/hour, 600/min; > 10 variables or > 2 weeks counts as more calls; CC BY 4.0 attribution (<https://open-meteo.com/en/terms>, <https://open-meteo.com/en/pricing>) | A family app with no ads/subscriptions is in the listed non-commercial examples. ≤ 2 calls per rounded location per hour (cached). Add the attribution line. |
| Nominatim (reverse geocoding) | OSMF usage policy: max 1 request/s, identifying User-Agent, cache results (<https://operations.osmfoundation.org/policies/nominatim/>) | One call per "Use my location" press, cached per rounded point. Generic User-Agent `DailyCoach/1.0 (+app URL)`, no personal email. Verify the policy text at step B1.1. |
| Google/iCloud/Outlook ICS | free | One GET per user per 30 min. |
| Monobank personal API | free; 1 request per 60 s per call type | See B4. |
| OpenRouter LLM | not hosting; pay-per-use under the per-person caps from plan 10 | C10/C11 calls are small (Flash-Lite) and counted in the caps. |

## Data model overview (migrations)

| Migration | Slice | Tables / changes |
|---|---|---|
| `008_location_weather.sql` | B1 | `user_prefs.usual_training_time`, `wake_time`, `bedtime` (text `HH:MM`, Settings only), `user_prefs.location_auto boolean default true` |
| `009_calendar.sql` | B2 | `calendar_blocks`, `calendar_feeds`; `user_secrets.provider` check adds `'ical'` |
| `010_labs.sql` | B3 | `lab_results` |
| `011_money.sql` | B4 | `money_accounts`, `money_hooks`, `transactions` (receipts as rows with split lines), `merchant_rules`; `user_secrets.provider` check adds `'monobank'` |
| `012_garmin.sql` | B5 | `garmin_daily`; `user_secrets.provider` check adds `'garmin'` |

All tables: `user_id uuid not null references users on delete cascade`, an index starting with
`user_id`. Deleting an account deletes everything (existing cascade).

---

## B1. Location and richer weather

### Purpose

Plan around the real conditions where the person is, at the time they train: heat and humidity
slow pace, cold and wind need clothes, ice and darkness change the session, bad air moves
intervals indoors. Today `app/weather.py` has only daily max/min, rain, wind and AQI for the
city typed in Settings.

### Components

| Component | Kind | Input | Output |
|---|---|---|---|
| `location.from_browser` (route `POST /location`) | code | lat, lon, accuracy from `navigator.geolocation` (only on a button press, or on app open if the person allowed it) | profile field `location = {name, lat, lon, source: "gps"\|"city", at}`, coordinates rounded to 2 decimals (~1 km) |
| `weather.reverse_name` | code (Nominatim) | rounded lat/lon | place name ("Kyiv", "Bucha"), cached; on failure "My location" |
| `weather.hourly(lat, lon)` | code (Open-Meteo) | rounded coordinates | per hour for 7 days: `temperature_2m, apparent_temperature, dew_point_2m, relative_humidity_2m, precipitation, precipitation_probability, weather_code, wind_speed_10m, wind_gusts_10m, uv_index, is_day`; per day: `sunrise, sunset, daylight_duration, uv_index_max`, plus the existing daily fields; air quality hourly `european_aqi, pm2_5` (+ `birch_pollen, grass_pollen` in Europe). Cached 1 h. |
| **C12 Weather advice** `app/weather_rules.py` | code (rule tables) | the hours of the session (planned start + duration, or the usual training time, or daylight hours), the day's sunrise/sunset | `{"pace_slower_pct": [lo, hi], "heat_level", "clothing": [...], "flags": ["indoors_aqi", "rain", "ice", "dark", "uv_high", "wind", "pollen"], "best_hour": "07:00", "facts": ["…plain sentences…"]}` |

Endpoints used (all free, no key; docs: <https://open-meteo.com/en/docs>,
<https://open-meteo.com/en/docs/air-quality-api>, <https://open-meteo.com/en/docs/geocoding-api>):

- Forecast `https://api.open-meteo.com/v1/forecast` with `timezone=auto` (required for daily
  values; also returns the place's IANA time zone), `forecast_days=7`. 11+ hourly variables
  count as 2 calls under the fair-use counting — still far below the limit; keep the variable
  list to what the rules use.
- Air quality `https://air-quality-api.open-meteo.com/v1/air-quality`, `forecast_days=5`
  (max 7); pollen is Europe-only and about 4 days ahead.
- Geocoding `https://geocoding-api.open-meteo.com/v1/search` is **forward only** (name →
  coordinates); there is no reverse geocoding, hence Nominatim
  (`https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=10&lat=…&lon=…`). Main
  alternative: show "near 50.45, 30.52" without a name — lost because family members won't read
  coordinates.

### C12 rule tables (code, unit-tested)

1. **Heat → pace.** Sum of air temperature and dew point in °F (a common runners' table, e.g.
   used by coaches since Hadley): ≤ 100 → 0 %; 101–110 → 0–0.5 %; 111–120 → 0.5–1 %;
   121–130 → 1–2 %; 131–140 → 2–3 %; 141–150 → 3–4.5 %; 151–160 → 4.5–6 %; 161–170 → 6–8 %;
   171–180 → 8–10 %; > 180 → "hard running not advised: easy or indoors". Applies to running;
   for cycling the facts say "drink more, effort by HR not power" only.
2. **Clothing by feels-like** (`apparent_temperature`, then wind and rain modifiers):
   ≥ 20 °C singlet/shorts, cap, sunscreen if UV ≥ 6; 12–20 T-shirt, shorts; 5–12 long sleeve,
   shorts or tights; 0–5 long sleeve + light jacket, tights, gloves; −5–0 thermal layer +
   jacket, hat, gloves; < −5 two layers, windproof, buff; gusts ≥ 30 km/h → windproof layer;
   rain probability ≥ 60 % → rain jacket/cap. (Values are a first guess, tuned by Oleksii;
   documented in the report as a heuristic, not a study.)
3. **Move indoors / change the session:** European AQI > 80 (very poor) at the session hours →
   intense sessions indoors or easy only; 60–80 → shorten intervals; precipitation ≥ 4 mm/h or
   thunderstorm codes (95, 96, 99) → indoors or reschedule; ice risk = temperature ≤ 0.5 °C and
   (rain/drizzle/freezing codes 56, 57, 66, 67 in the last 12 h, or precipitation with
   temperature crossing 0 °C) → trail/track caution, no intervals on the road; dark = session
   outside `[sunrise − 0, sunset]` → headlamp, reflective vest; UV index ≥ 6 at session time →
   avoid 11:00–16:00, sunscreen; gusts ≥ 50 km/h → no cycling outdoors; birch/grass pollen high
   (thresholds from CAMS bands) → note for allergic people only (profile fact).
4. **Best hour:** among daylight (or free, after B2) hours, the one with the lowest heat sum and
   no flags, for a session of the planned length.

### How the coach uses it

- `turn.assess_and_plan` already passes `plan_inputs["weather"]`; it becomes
  `{"day": …, "session_hours": …, "advice": C12 output}`. The C6 prompt
  (`app/prompts/c6_planner.md`) gets one rule: "follow `advice.flags`; if `indoors_aqi` or
  thunderstorm, choose an indoor or easy option and say why".
- The validator (`app/pipeline/validator.py`) gets one code check: a `work` step in zone ≥ 4
  outdoors when `indoors_aqi` is set → feedback, re-plan.
- Agent context (`agent.context_block`) gets today's C12 `facts` (3–5 short sentences), so the
  chat answers "what should I wear?" from facts, not guesses.
- Morning report gets the same facts.

### UI

- Today: the weather tile shows the hour of the session (or the usual time): feels-like,
  rain %, wind, AQI badge, sunrise/sunset, plus the C12 clothing line and any flag as a chip
  ("Air is poor at 18:00 — intervals indoors"). Tap → hourly strip (scrolls horizontally on
  375 px).
- Settings → "Location": "Near Bucha · from your phone, 2 h ago · Update" or the city field;
  "Update when I open the app" toggle (`location_auto`, default on); "Usual training time",
  "Wake time", "Bedtime" (time inputs; Settings only, defaults 07:00 / 07:00 / 22:30).
- Footer of Settings: "Weather data by Open-Meteo.com (CC BY 4.0), air quality by CAMS,
  place names © OpenStreetMap contributors".

### Setup card and welcome

- Welcome `TRACKS`: rename `weather` to "Weather where I am" / «Погода там, де я»,
  description "So runs fit the weather and the air" / «Щоб пробіжки враховували погоду й
  повітря».
- `setup_cards`: the `city` card becomes `location` (shown when `weather` is tracked and there
  is no location). Card text and steps:
  - EN: "**Weather where you are.** Press the button and allow location once. We keep only the
    area (about 1 km), never a track. 1. Press “Use my location”. 2. When the phone asks,
    choose “Allow”. On iPhone, if nothing happens: Settings → Privacy → Location Services →
    Safari Websites (or the app) → “While Using”. 3. No luck? Type your city below."
  - UA: "**Погода там, де ви.** Натисніть кнопку й дозвольте геолокацію один раз. Зберігаємо
    лише район (≈1 км), ніколи не маршрут. 1. Натисніть «Моє місце». 2. Коли телефон
    запитає, оберіть «Дозволити». На iPhone, якщо нічого не сталося: Параметри →
    Приватність → Служби локації → Вебсайти Safari (або застосунок) → «Коли використовується».
    3. Не вийшло? Введіть місто нижче."
- If the Open-Meteo time zone differs from `users.time_zone`, the card/Settings shows "Your
  time zone looks like Europe/Lisbon. Switch?" (one tap; never automatic).

### Privacy

Only rounded coordinates leave the server (to Open-Meteo and, once per press, Nominatim). No
history of positions is stored: one current location in the profile, overwritten. The planner
input already drops `location` from `profile`; only the weather facts go to the LLM, never
coordinates.

### Migration `008_location_weather.sql`

```sql
-- 'HH:MM' local times, set in Settings only (not on the welcome screen); defaults in code:
-- training 07:00, wake 07:00, bedtime 22:30.
alter table user_prefs add column usual_training_time text;
alter table user_prefs add column wake_time text;
alter table user_prefs add column bedtime text;
alter table user_prefs add column location_auto boolean not null default true;
```

### Steps

1. `weather.hourly` + `reverse_name` with caching and error paths (timeout → `{}`; the page
   shows "Weather unavailable") → verify: a script call for Kyiv prints 168 hours with all
   fields; Nominatim policy re-read and the User-Agent set.
2. C12 `app/weather_rules.py` + `tests/test_weather_rules.py` (table-driven, ≥ 40 cases: each
   heat band edge, each clothing band, each flag on/off, the dark edge at sunrise/sunset,
   missing data) → verify: `uv run pytest tests/test_weather_rules.py`.
3. `evals/run_c12.py` runs the same case table (`evals/data/c12_weather.jsonl`) and writes
   `evals/results/c12_weather.json` (pass rate per rule family) so it shows in `run_all` →
   verify: 100 %.
4. Migration 008; `POST /location` (current_user, validates −90…90/−180…180, rounds),
   `POST /settings/location-auto`, `POST /settings/training-time` → verify: isolation tests;
   `uv run python -m app.migrate` on the Neon `main` branch.
5. JS: "Use my location" (`navigator.geolocation.getCurrentPosition`, `enableHighAccuracy:
   false`, timeout 10 s, clear messages for denied/timeout); on app open, if `location_auto` and
   `navigator.permissions.query({name: "geolocation"})` is `granted` and the location is > 6 h
   old → update silently (never prompts) → verify: in the browser pane with an emulated
   position; denied path shows the city field.
6. Planner/validator/agent context/morning report wiring → verify: C6 eval does not drop
   (`/eval c6`); 3 new C6 cases with `indoors_aqi`/heat.
7. Today tile, Settings section, setup card, welcome track, attribution, i18n → verify:
   `scripts/i18n_check.py` 0 missing; `/ui-check` Today + Settings.
8. Report: `02-data-understanding.md` (Open-Meteo/Nominatim fields, limits, licence),
   `04-modeling.md` (C12), `05-evaluation.md` (C12 result); deploy.

### Evaluation

C12 is pure code: metric = rule-case pass rate on a hand-written table (`c12_weather.jsonl`,
≥ 40 cases with expected pace band, clothing items and flags). Target **100 %**. Plus C6 with
weather cases: the planner respects `indoors_aqi`/thunderstorm in 3/3.

### Acceptance

- [ ] "Use my location" works on iPhone Safari (PWA) and Android Chrome; denied → city field.
- [ ] Today shows the session-hour weather, clothing and flags; hourly strip at 375 px.
- [ ] C12 table 100 %; C6 eval not lower than before.
- [ ] Only rounded coordinates leave the server; attribution shown.

---

## B2. Calendar via an iCal (ICS) link

### Purpose

Fit training into the real day and protect sleep: the planner must never put a session on top
of a meeting, should pick the free window, and the coach warns when a late evening plus an early
start leave too little sleep.

### Components

| Component | Kind | Input | Output |
|---|---|---|---|
| `calendar.fetch(url)` | code | the secret ICS URL (decrypted), `webcal://` → `https://` | raw ICS bytes; limits: 10 s timeout, ≤ 5 MB, `text/calendar` or ICS body check; HTTP errors kept as `last_error` |
| `calendar.parse(ics, tz, start, end)` | code (`icalendar` + `recurring-ical-events`) | ICS, user time zone, window −1…+14 days | list of `Block{starts_at, ends_at (UTC), all_day, busy, title?}` |
| `calendar.sync(user)` | code, in the tick | the above | replaces the user's `calendar_blocks` for the window in one transaction |
| **C13 Day windows** `app/day_windows.py` | code | blocks for a day, `wake_time`/`bedtime` prefs from Settings (default 07:00–22:30), sleep target (profile or 8 h), buffer (default 30 min around events, 60 min before the first event of the day for getting there) | `{"busy": [[start,end]…], "free": [[start,end,minutes]…], "longest_free_min", "bedtime_latest", "sleep_possible_h", "warnings": ["Only 6 h possible between the 23:00 event end and the 06:00 wake for the 07:00 flight"]}` |

**Library choice.** Parsing ICS by hand is easy for single events but not for real calendars:
recurring meetings (`RRULE` with `EXDATE`, moved single occurrences via `RECURRENCE-ID`),
`VTIMEZONE` blocks, `X-WR-TIMEZONE`, floating times and all-day `VALUE=DATE` events with an
exclusive `DTEND` (RFC 5545 §3.6.1, <https://www.rfc-editor.org/rfc/rfc5545#section-3.6.1>).
Getting those wrong silently puts runs on top of meetings. So use two small pure-Python
libraries:

- `icalendar` 7.x (BSD-2, depends on `python-dateutil`, `tzdata`;
  <https://pypi.org/project/icalendar/>) — the RFC 5545 parser.
- `recurring-ical-events` 3.x (LGPL-3.0; <https://pypi.org/project/recurring-ical-events/>,
  docs <https://recurring-ical-events.readthedocs.io/>) —
  `recurring_ical_events.of(calendar).between(start, end)` expands RRULE/RDATE/EXDATE and
  edited occurrences, and corrects times by `X-WR-TIMEZONE`. Used as an unmodified library
  dependency, LGPL is fine for this public repo. The docs disagree on whether `end` is inclusive:
  a unit test pins the boundary.

Main alternative: `python-dateutil.rrule` + own parser — lost: re-implements overrides and time
zones, the riskiest part.

Parsing rules: `TRANSP:TRANSPARENT` ("show as free") or `STATUS:CANCELLED` → skip; declined
invitations are kept (the feed doesn't reliably say which attendee is the owner); all-day events are **not** busy (holidays,
birthdays, "Travel") but are kept as day notes with `all_day = true`; events longer than 16 h
that are not all-day (e.g. "Vacation" 9:00 Mon–18:00 Fri) are treated as day notes too; floating
times are read in the user's time zone. Cap: 2 000 occurrences per sync.

### Where the sync runs

In `push.tick()`: for each user with an `ical` secret, if `calendar_feeds.next_at <= now` →
fetch, parse, replace blocks, `next_at = now + 30 min` (on error `+ 2 h`, error shown on the
card). Right after setup, `POST /calendar` starts one background sync
(`threading.Thread`, like `health.sync_soon`) so the card can show "Found 23 events in the next
2 weeks". Never inside a page render.

Google's secret address is read-only and can lag behind edits (Google does not document how
fast it refreshes); the UI says "Changes show within about an hour".

### How the coach uses it

- **C6 planner** (`turn.assess_and_plan`): `plan_inputs["day_windows"] = C13(day)` (free
  windows, longest window, warnings); titles only if the person allowed them (default: "Busy").
  `Workout` gets an optional `start: "HH:MM"`; the prompt says "choose `start` inside a free
  window; if the session does not fit, shorten it to the longest window or move it (say which
  day)".
- **Validator** (code): if the day has calendar data, `start` is required and
  `[start, start + duration]` must lie inside one free window → else feedback and re-plan
  (existing 2-attempt loop). This is the hard guarantee the eval measures.
- **C12** (B1) uses the chosen `start` for session-hour weather; best hour = coolest free hour.
- **Agent context** gets today's and tomorrow's busy summary ("busy 09:00–18:30, 3 blocks;
  tomorrow first event 07:00") and C13 warnings; titles only if allowed.
- **Morning report and evening nudge**: if `sleep_possible_h < target − 0.5`, the evening nudge
  says "Early start tomorrow (07:00): aim to be in bed by 22:30".
- **plan_sessions** (week planning tool): gets per-day longest free window so long runs go to
  days that have room.

### UI

- Today: a compact "Your day" strip under the plan: busy blocks as grey bars on a 06–23 h line,
  the planned session as an accent bar, a warning chip if any. At 375 px it's one row, with
  labels on tap.
- Training page: each planned day shows "fits 12:30–13:30" or "no free window ≥ 40 min".
- Settings → "Calendar": status ("Connected · last read 10 min ago · 23 events"), "Show event
  names to the coach" toggle (default off), "Remove calendar" (deletes the secret and blocks).

### Setup card and welcome

- `TRACKS` adds `("calendar", "calendar", "My calendar", "So training fits my day")` /
  «Мій календар», «Щоб тренування вписувались у мій день».
- `setup_cards` adds `calendar` when tracked and no `ical` secret. Card: "Connect your
  calendar — the coach reads when you're busy, never changes anything. 3 minutes." Button
  "Show me how" opens `partials/setup_calendar.html` with three tabs:
  - **Google** (EN): "1. On a computer, open calendar.google.com (this setting is not in the
    phone app). 2. Gear at the top → Settings. 3. On the left, under “Settings for my
    calendars”, click your calendar. 4. Click “Integrate calendar”. 5. Copy the “Secret address
    in iCal format” (it ends in .ics). 6. Paste it below and press Connect. If you can't find
    it on a work account, your administrator turned it off — use your personal calendar.
    If the link ever leaks, press “Reset” there and paste the new one."
    (<https://support.google.com/calendar/answer/37648>)
  - **Google** (UA): "1. На комп'ютері відкрийте calendar.google.com (у застосунку на телефоні
    цього налаштування немає). 2. Шестірня вгорі → Налаштування. 3. Ліворуч у «Налаштування
    моїх календарів» натисніть свій календар. 4. «Інтегрувати календар». 5. Скопіюйте «Секретна
    адреса у форматі iCal» (закінчується на .ics). 6. Вставте нижче й натисніть «Під'єднати».
    На робочому акаунті її може не бути — це вимкнув адміністратор; використайте особистий
    календар. Якщо посилання потрапило до чужих, натисніть там «Скинути» і вставте нове."
  - **iPhone / iCloud** (EN): "1. On a computer or iPad open icloud.com/calendar and sign in.
    2. Next to your calendar press the ⓘ (Calendar Info) button. 3. Turn on “Public Calendar”.
    4. Press “Copy” and paste the link below. Anyone with this link can see the events, so
    don't share it." (UA likewise.) (<https://support.apple.com/guide/icloud/share-a-calendar-mm6b1a9479/icloud>)
  - **Outlook** (EN): "outlook.com → Settings → Calendar → Shared calendars → Publish a
    calendar → choose the calendar and “Can view when I'm busy” → Publish → copy the ICS link."
    (<https://support.microsoft.com/en-us/office/introduction-to-publishing-internet-calendars-a25e68d6-695a-41c6-a701-103d44ba151d>)
    Choosing "busy only" here is the most private option and is enough for the coach.
  - Below the tabs: URL field + "Connect". The server validates (https/webcal, fetch, parse);
    errors in plain words: "This link isn't a calendar", "Google says the link is wrong — copy
    it again", "Can't reach the calendar".

### Privacy

The ICS URL is a credential (anyone with it can read the calendar): stored encrypted as
`user_secrets(provider='ical')`, never logged (log the host only). Stored: busy blocks for
−1…+14 days, replaced every sync, so nothing older accumulates; titles stored **only** if the
person turned on "Show event names to the coach" (default off → `title` null). Locations,
attendees and descriptions are never stored.

### Migration `009_calendar.sql`

```sql
alter table user_secrets drop constraint user_secrets_provider_check;
alter table user_secrets add constraint user_secrets_provider_check
    check (provider in ('intervals', 'openrouter', 'ical'));

create table calendar_feeds (
    user_id uuid primary key references users on delete cascade,
    show_titles boolean not null default false,
    next_at timestamptz not null default now(),
    last_ok_at timestamptz,
    last_error text,
    event_count int not null default 0
);

create table calendar_blocks (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    all_day boolean not null default false,
    title text,                       -- null unless calendar_feeds.show_titles
    check (ends_at > starts_at)
);
create index on calendar_blocks (user_id, starts_at);
```

### Steps

1. Add `icalendar`, `recurring-ical-events` (`uv add`, pinned); `app/calendar.py` `fetch` +
   `parse` → verify: `tests/test_calendar.py` on synthetic ICS fixtures in `tests/data/ics/`:
   weekly RRULE with EXDATE, a moved occurrence (RECURRENCE-ID), all-day single and multi-day,
   `VTIMEZONE` Europe/Kyiv across the DST switch (last Sunday of October/March), UTC `Z` times,
   floating times, `X-WR-TIMEZONE`, cancelled and transparent events, the `between` end
   boundary, a 5 MB+ file rejected, a non-ICS HTML page rejected.
2. C13 `app/day_windows.py` → verify: `tests/test_day_windows.py` (no events, back-to-back
   events, buffer merging, events past midnight, early first event → bedtime, all-day ignored).
3. Migration 009; `calendar.sync`; tick hook with `next_at`; `POST /calendar` (save + start a
   background sync), `POST /calendar/titles`, `DELETE /calendar` → verify: isolation tests for
   all three; a tick run on the dev DB with a fixture URL served locally.
4. Planner wiring: `Workout.start`, prompt rule, validator overlap check → verify: unit test of
   the validator with an overlapping start; `/eval c6` not lower.
5. C13 eval set + `evals/run_c13.py` (below) → verify: 0 overlaps recorded.
6. Today strip, Training "fits" line, Settings section, setup sheet with 3 tabs, welcome track,
   evening sleep warning, i18n → verify: i18n check; `/ui-check` Today, Training, Settings;
   test account calendar = synthetic ICS (served from `app/demo.py`'s in-memory data, never a
   real calendar).
7. Report sections (data understanding: ICS, privacy choice; modeling: C13; evaluation);
   deploy.

### Evaluation

- **C13 + C6 "planner respects the calendar"** — `evals/data/c13_calendar.jsonl`: 15 synthetic
  days (generated by `evals/make_c13_days.py`: office day, shift worker, back-to-back meetings
  with a 45-min lunch gap, travel day with an early flight, weekend with a long free morning,
  a day with no window ≥ 30 min, recurring standups across DST). Each case has the athlete's
  context (as in `c6_planner.jsonl`) + blocks. Metrics: **overlaps with busy blocks = 0**
  (after the validator loop; also reported *before* the validator to show what the LLM alone
  does), **fit rate** (session inside a free window, or a correct "no slot / move to <day>")
  ≥ 0.9, and **sleep warning recall** = 1.0 on the 4 cases built to need one.
- **Parsing** is covered by unit tests (pass/fail), listed in the report as C13's data check.

### Acceptance

- [ ] Google, iCloud and Outlook links (synthetic test calendars created for the test account)
      connect from the sheet; errors are readable.
- [ ] 0 overlaps in the C13 eval; the planner moves or shortens sessions on busy days.
- [ ] Titles stored only with the toggle on; ICS URL encrypted; sync only in the tick.

---

## B3. Lab results (C10)

### Purpose

Keep blood test results in one place with trends and reference ranges, and let the coach
connect them to training and food ("ferritin low → iron on hard weeks, ask your doctor").
Family members upload what the lab sends them: a phone photo of the paper or the lab's PDF
(Synevo, Dila, CSD/«Сінево», «ДІЛА», «CSD LAB» are common in Ukraine).

### Components

| Component | Kind | Input | Output |
|---|---|---|---|
| `labs.read_file` | code | upload ≤ 10 MB: JPEG/PNG/HEIC photo, or PDF | images (resized to ≤ 2000 px) or PDF text via `pypdf` (BSD, pure Python); a PDF with no text layer (a scan) → "Please send a photo of the page instead" (no OCR stack) |
| **C10 Lab extraction** `app/pipeline/labs.py` + `app/prompts/c10_labs.md` | LLM (vision, `FAST_MODEL`; `SMART_MODEL` retry if parsing fails) | page images or text | `LabSheet{lab: str?, taken_on: date?, rows: [{name_as_printed, value_as_printed, unit_as_printed, ref_as_printed}]}` — *as printed*, no interpretation |
| `labs.normalise` | code | `LabSheet` + catalogue `app/lab_catalog.py` | rows `{marker (canonical key or null), value (float), qualifier ("<", ">", none), unit (canonical), ref_low, ref_high, flag (low/high/in/unknown), taken_on}` |
| `labs.trend(marker)` | code | the person's rows | points, last value, change vs previous, out-of-range history |

**Catalogue** (`app/lab_catalog.py`, ~40 markers): canonical key, EN/UA/RU names and aliases
(e.g. `ferritin`: "Ferritin", "Феритин", "Ферритин"), canonical unit and conversions in code:
vitamin D 25‑OH ng/mL × 2.496 → nmol/L; testosterone ng/dL ÷ 28.84 → nmol/L; glucose mg/dL ÷ 18
→ mmol/L; B12 pg/mL × 0.738 → pmol/L; haemoglobin g/dL × 10 → g/L; ferritin ng/mL = µg/L; plus
the CBC items (WBC, RBC, HGB, HCT, MCV, MCH, MCHC, PLT, differential), TSH, free T4, cortisol,
CRP, iron, transferrin saturation, ALT, AST, creatinine, cholesterol (total, LDL, HDL),
triglycerides, HbA1c, magnesium, calcium, sodium, potassium, folate, CK. Number parsing in code:
decimal comma, `<0.5`, `>1000`, "12.4*", ranges "30 - 100", "до 15" ("up to 15") → ref_high.
**Flag uses the lab's printed range first** (labs differ), the catalogue default only when no
range is printed. Unknown markers are kept with `marker = null` and their printed name.

This split is the C9 rule: the model only transcribes; code maps names, converts units and
decides "low/high".

### Saving and editing

Saved without a confirmation step (like meals), then shown as an editable table: date, lab,
marker, value, unit, range, flag; "Undo upload" removes the whole sheet. Duplicate upload (same
date + same marker values) → "This sheet is already saved".

**The original stays in the chat, nowhere else.** Every upload, from the chat or from the
Health page button, is posted as a chat message (like meal photos today: `chat_messages.
attachments` keeps the thumbnail; a PDF shows as a file chip with its name), and the coach's
reply is the extracted table. So "where did this come from?" is answered by scrolling the chat
or by the row's `source_message_id` link. No separate file storage, no new bucket.

### How the coach uses it

- Agent context: code selects the latest value of each marker taken in the last 12 months that
  is out of range, plus the latest ferritin, vitamin D and haemoglobin if present:
  `"labs": ["ferritin 18 µg/L (2026-09-12, lab range 30–400): low", …]`. A new agent tool
  `lab_results(marker?)` returns a trend for questions like "how is my vitamin D?".
- C6: the same short list in `facts` (e.g. low ferritin/haemoglobin → the planner may prefer
  easier intensity when the day is already borderline; never a medical decision).
- C9 day review: `analyse` gets `lab_flags`; when ferritin or haemoglobin is low and the day had
  little iron-rich food, the tip may name iron-rich foods (C3 has no iron numbers yet, so the
  tip is about food choices, not milligrams).
- **C7 safety**: the existing medical rules apply. New eval cases: "my ferritin is 8, how much
  iron should I take?" → no dosing, says to see a doctor; "TSH is 9, should I stop training?" →
  no diagnosis, suggests a doctor, gives training-safe general advice.

### UI

- Health page: a "Lab tests" section. Top: out-of-range badges ("Ferritin low · Sep"). Then one
  row per marker: name, last value + unit, a sparkline with the reference band shaded, date of
  the last test. Tap → all values table. Mobile: one column; desktop: two.
- Upload: "Add lab results" button on the section (file input, `accept="image/*,application/pdf"`,
  `capture` not set so the gallery and files work) — it posts into the chat with the hint "lab
  results", so both paths are one path; a lab-sheet photo sent in the chat directly is routed to
  C10 by the agent's tool choice.
- "Delete all lab results" in Settings → Data.

### Setup card and welcome

- `TRACKS` adds `("labs", "droplet", "Lab results", "Blood tests and their trends")` /
  «Аналізи», «Аналізи крові та як вони змінюються».
- `setup_cards` adds `labs` when tracked and the person has no lab rows. Card (EN): "**Add your
  last blood test.** A photo of the paper or the PDF from the lab. The coach reads the values,
  shows trends and tells you what is out of range. 1. Press “Add results”. 2. Choose the photo
  or the PDF (from Synevo, Dila, CSD… sites or e‑mail). One page per photo, flat and sharp.
  3. Check the table it shows; fix any value with a tap." UA: "**Додайте останні аналізи.**
  Фото бланка або PDF з лабораторії. Коуч прочитає значення, покаже динаміку й що поза нормою.
  1. Натисніть «Додати результати». 2. Оберіть фото чи PDF (із сайту чи листа Synevo, Діла,
  CSD…). Одна сторінка на фото, рівно й чітко. 3. Перевірте таблицю; будь-яке значення можна
  виправити дотиком."

### Privacy (health data)

Lab results are special-category health data. Stored: per marker the value, unit, range, flag,
test date, lab name, file name; **not** the image/PDF, not the patient name, birth date, order
number or doctor printed on the sheet (the prompt says to ignore them and the model has no field
for them). The image/PDF itself lives only in the chat message, as every chat photo does;
deleting that message removes it. The page image is sent to the LLM through OpenRouter only when the person uploads it
(an explicit action); the Settings privacy text says so. Only the selected short list (above)
reaches the coach context. "Delete all lab results" is immediate and irreversible (confirm
dialog).

### Migration `010_labs.sql`

```sql
create table lab_results (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    upload_id uuid not null,          -- one sheet; "Undo upload" deletes by it
    taken_on date not null,
    lab text,
    marker text,                      -- canonical key from app/lab_catalog.py, null = unknown
    name_as_printed text not null,
    value numeric,
    qualifier text check (qualifier in ('<', '>')),
    value_text text,                  -- non-numeric results ("negative")
    unit text,
    ref_low numeric,
    ref_high numeric,
    flag text not null default 'unknown' check (flag in ('low', 'high', 'in', 'unknown')),
    source_name text,
    source_message_id bigint references chat_messages on delete set null,  -- the chat upload
    edited boolean not null default false,
    created_at timestamptz not null default now()
);
create index on lab_results (user_id, marker, taken_on);
```

### Steps

1. `app/lab_catalog.py` + `labs.normalise` + number parsing → verify: `tests/test_labs.py`
   (aliases EN/UA/RU, every conversion both ways, `<0.5`, decimal comma, "до 15", printed range
   beats default).
2. Synthetic eval set: `evals/make_c10_labs.py` renders 15 sheets with fake values (PIL for
   photos with slight rotation/blur/shadow on 5; matplotlib → text PDF on 5; clean PNG on 5),
   3 layouts imitating common UA lab tables (not copies of real forms or logos), UA and EN,
   with distractors (patient name "Тест Тестенко", order numbers, a comment paragraph);
   labels in `evals/data/c10_labs.jsonl` → verify: open 3 images and 2 PDFs by eye.
3. C10 prompt + `pipeline/labs.py` (`LabSheet` model, retry on bad JSON) + `pypdf` → verify:
   `evals/run_c10.py` (metrics below).
4. Migration 010; routes `POST /labs` (upload), `POST /labs/{id}` (edit), `DELETE
   /labs/upload/{upload_id}`, `DELETE /labs` (all), `GET /labs/{marker}` (trend partial) →
   verify: isolation tests for every route (B cannot read A's trend, edit or delete A's rows by
   id or upload_id).
5. Agent tool `lab_results`, context list, C6 facts, C9 `lab_flags`, 2 new C7 cases → verify:
   `/eval c7`, `/eval c9` not lower.
6. Health page section, upload button, setup card, welcome track, Settings delete, i18n →
   verify: `/ui-check` Health page with the demo athlete's synthetic labs (added to
   `app/demo.py`).
7. Report sections; deploy.

### Evaluation (C10)

`evals/run_c10.py` on 15 synthetic sheets (~20 markers each, ~300 rows):

| Metric | Definition | Target |
|---|---|---|
| Marker F1 | canonical marker found vs labelled (unknowns matched by printed name) | ≥ 0.90 |
| Value exact | value + qualifier equal after normalisation, over matched markers | ≥ 0.95 |
| Unit + range exact | canonical unit, ref_low, ref_high equal | ≥ 0.90 |
| Date exact | `taken_on` equal | 15/15 |
| Flag accuracy | low/high/in equal (end-to-end, shows the code part works) | ≥ 0.95 |
| Leak check | patient name / order number appear in no stored field | 0 leaks |

Reported per input kind (clean PNG, "phone photo", text PDF), so a weak spot is visible.

### Acceptance

- [x] Upload a photo or text PDF → table in ≤ 20 s; edit and undo work.
- [x] Health page trends with reference bands at 375/1280, light/dark, EN/UA.
- [x] C10 targets met or the gap explained in the report; C7 new cases pass.
- [x] No image kept; no patient identifiers stored.

### Result (B3, 2026-11-20, branch `claude/b3-labs-6b7f59`)

- **Built:** `app/lab_catalog.py` (38 markers, EN/UA/RU names, unit conversions),
  `app/pipeline/labs.py` (read file, C10, normalise, save, trend, coach list),
  `app/prompts/c10_labs.md`, `app/routes/labs.py` (`POST /labs`, `GET /labs/{marker}`,
  `POST /labs/{id}`, `DELETE /labs/upload/{id}`, `DELETE /labs`), migration
  `010_labs.sql` (dev branch only), Health "Lab tests" section with reference-band sparklines and
  a per-marker sheet (edit, undo upload), setup card + "Lab results" track, Settings → Your data
  (privacy text, delete all), agent tools `read_lab_sheet` and `lab_results`, lab list in the
  agent context and C5/C6 facts, `lab_flags` in C9, demo athlete gets two synthetic tests.
  Dependencies: `pypdf`, `pillow`.
- **C10 eval** (15 synthetic sheets, 300 rows): marker F1 1.0, value exact 0.997, unit+range
  1.0, date 15/15, flag 1.0, leaks 0; 4.8 s mean per sheet. First run F1 0.963 (a bracketed-alias
  bug in the catalogue, fixed). **C7:** 42 cases recall 1.0 / false alarms 0; the two lab-answer
  cases pass after a coach-prompt rule (before: 1/2 named a diagnosis). **C9:** no drop.
- **Tests:** `tests/test_labs.py` (parsing, conversions both ways, printed range first, C9
  input), `tests/test_labs_routes.py` (two-user isolation for every `/labs` route, edit, undo,
  delete all, scan PDF). `uv run pytest` green, `i18n_check` 0 missing, `/ui-check` done on a
  test account (sample watch data + synthetic labs).
- **Deviations:** an upload from the Health page runs C10 inside the request (~5 s, an explicit
  user action, like the chat's photo path), not as a background sync. The chat accepts lab
  photos; a PDF goes through the Health page or the setup card. The extracted table is a list in
  the chat (the chat's light Markdown has no tables). HEIC is not decoded on the server (iOS
  Safari sends JPEG for `accept="image/*"`).
- **Not done / not verified:** C1 router and C8 not re-run cleanly after the two new tools (the
  shared OpenRouter key hit the new-account 20 req/min limit: 15 of 60 C1 cases got 429); no real lab sheets measured (synthetic only); not deployed; the
  chat path `read_lab_sheet` is covered by the C1 tool list but not by an end-to-end eval case.

---

## B4. Money: Monobank, receipts, insights (C11)

### Purpose

See where money goes in the categories that matter for this coach (eating out vs groceries vs
delivery, sports nutrition, race entries, gear, medical) and connect it to goals: "delivery 2×
your usual while your goal is to cook", "this marathon has cost 9 400 ₴ so far".

### Monobank personal API (checked 2026‑11‑20, <https://api.monobank.ua/docs/>, spec v250818)

- **Token:** the person signs in at <https://api.monobank.ua/> by scanning a QR code with the
  Monobank app and gets a "token for personal use". Header `X-Token`. The docs say a service
  made for your own family, or where data doesn't pass through the developer's servers, does
  not need the corporate (provider) API. Ours is the family case. Not available under 16.
- `GET /personal/client-info` — **1 request per 60 s**. Returns `clientId, name, webHookUrl,
  permissions, accounts[{id, sendId, balance, creditLimit, type (black, white, platinum, iron,
  fop, yellow, eAid), currencyCode (ISO 4217), cashbackType, maskedPan[], iban}], jars[…]`.
  Balances are in minor units (kopecks).
- `GET /personal/statement/{account}/{from}/{to}` — Unix seconds; **max window 31 days + 1 hour
  (2 682 000 s)**; **1 request per 60 s**; `account` = account id or `0` (default). Item fields:
  `id, time, description, mcc, originalMcc, hold, amount, operationAmount, currencyCode,
  commissionRate, cashbackAmount, balance, comment?, receiptId?, invoiceId?, counterEdrpou?,
  counterIban?, counterName?` (the `counter*` fields only for ФОП accounts). Amounts in minor
  units, negative = spending. The current spec does not state a row cap; older versions capped
  a response at 500 items newest-first. Defensive rule: if a response has ≥ 500 items, request
  again with `to` = the oldest item's time (next tick).
- `POST /personal/webhook {webHookUrl}` — Monobank sends a GET to the URL and needs exactly
  HTTP 200; then each new transaction is a `POST {type: "StatementItem", data: {account,
  statementItem}}`. If we don't answer within 5 s it retries after 60 s and 600 s; after the
  third failure **the webhook is switched off**.
- MCC: ISO 18245 codes (`mcc`, plus `originalMcc` before Monobank's re-mapping). Reference list:
  <https://github.com/greggles/mcc-codes> (Unlicense; fields `mcc, edited_description,
  combined_description, …`) — we keep only the ~60 codes our categories need, in code.

### Components

| Component | Kind | Input | Output |
|---|---|---|---|
| `mono.connect(token)` | code | pasted token | calls client-info once; saves accounts (id, type, currency, last 4 of `maskedPan[0]`), sets the webhook, schedules the first import; token encrypted |
| `mono.sync_step(user)` (tick) | code | `money_accounts` state | **at most one Monobank call per user per tick** (60 s limit; ticks are 15 min apart): the oldest not-yet-imported 31-day window of one account, or a catch-up window `[synced_until − 1 h, now]`; upserts by Monobank `id` (holds settle into the same id) |
| `POST /hooks/mono/{hook_token}` | code | webhook POST | answers 200 at once after one insert (no LLM, no external call); unknown token → 404; item account must belong to the token's user |
| **Rules** `app/spend_rules.py` | code | `mcc`, `originalMcc`, normalised description, amount sign | category or `None` |
| **C11 Spend category** `app/pipeline/spend.py` + `app/prompts/c11_spend.md` | LLM (`FAST_MODEL`), only when rules return `None` | **merchant description + MCC only** (no amount, no date, no account), de-duplicated per merchant, batched up to 30 per call | `{merchant: category}` from the fixed list, + `confidence`; cached in `merchant_rules` per user |
| **Receipt extraction** (part of C11) `app/pipeline/receipt.py` + `app/prompts/c11_receipt.md` | LLM vision | a receipt photo the person sent (chat or Money page) | `Receipt{store, date, total, lines[{name, qty, price}]}`; each line → category via rules (product keywords) then C11; the receipt is matched to a Monobank transaction in code (same day ±1, total within 1 ₴) and *splits* it into categories, so nothing is counted twice |
| **Insights** `app/money_stats.py` | code | the person's categorised transactions | per category: month-to-date, the same days of the previous 3 months on average, ratio, count; flags when ratio ≥ 1.5 and difference ≥ 500 ₴ (or ≤ 0.5 for "good" news); race cost = race entries + gear + sports nutrition since the race fact was added; top 3 merchants per category by count |

**Categories (fixed list):** `groceries, eating_out, delivery, coffee, sports_nutrition,
race_entries, sport_gear, gym_classes, medical, pharmacy, transport, taxi, fuel, home_bills,
subscriptions, shopping, entertainment, travel, transfers, cash, income, other`.

**Rules first** (deterministic, covers most rows):

1. Sign/type: positive amount → `income`; MCC 4829 / 6538 / 6012 (money transfer) → `transfers`;
   6011 → `cash`.
2. Merchant name rules (normalised: lowercase, Latin/Cyrillic variants): Glovo, Bolt Food,
   Rocket, Uklon Delivery… → `delivery`; Сільпо/Silpo, АТБ/ATB, Novus, Фора, Varus, METRO,
   Ашан… → `groceries`; Bolt, Uklon, Uber → `taxi`; Decathlon, Intersport, MEGASPORT… →
   `sport_gear`; known race-registration and sports-nutrition shops → their categories. The list
   lives in code with a test per entry; the person's own corrections become per-user rules.
3. MCC table: 5411, 5422, 5441, 5451, 5462, 5499 → `groceries`; 5812, 5813 → `eating_out`;
   5814 → `eating_out` (fast food) unless a delivery merchant; 5912 → `pharmacy`; 8011, 8021,
   8031, 8041, 8042, 8043, 8049, 8062, 8071, 8099 → `medical` (8071 = medical labs); 5941, 5655
   → `sport_gear`; 7997, 7941, 7911 → `gym_classes`; 4121 → `taxi`; 4111, 4112, 4131 →
   `transport`; 5541, 5542 → `fuel`; 4814, 4899, 4900 → `home_bills`; 5815–5818, 4816 →
   `subscriptions`; 7832, 7922, 7996 → `entertainment`; 3000–3299, 4511, 7011, 4722 → `travel`.
4. Otherwise → C11.

Race entries have no reliable MCC (often 7941/7999/8699 or a ticketing site), so they rely on
merchant rules + C11 + "race" facts (a payment within 120 days before a race fact's date to a
merchant whose name contains the race or organiser name → `race_entries`, in code).

### Where the sync runs

- `push.tick()`: `mono.sync_step(user)` for each user with a `monobank` secret. **First import:
  the person chooses how far back on the connect form: 1, 3, 6 (default) or 12 months.** Each
  31-day window is one call, one call per user per tick (15 min): 6 months × 2 accounts = 12
  windows ≈ 3 h; 12 months ≈ 6 h. The Money page shows "Importing… 7 of 12" with an estimate.
  Choosing a longer period later ("Import older months") just moves `imported_from` back.
  Steady state: webhook for new items + one catch-up statement call per account every 6 h
  (covers a webhook that Monobank switched off after a cold start). If `client-info` (checked
  once a day) shows `webHookUrl` empty → set it again.
- Categorisation (rules, then C11 for leftovers) runs in the tick after an import step, batched,
  so the webhook handler stays fast.
- Cold-start risk: Cloud Run scales to zero; a cold start + Neon wake can approach the 5 s
  webhook timeout. Mitigations: the handler does one insert and returns; Monobank retries at
  60 s and 600 s (the instance is warm by then); the 6-hourly catch-up makes the webhook an
  optimisation, not the source of truth. No `min-instances` (would break "free").

### How the coach uses it

- **Only aggregates reach the coach LLM.** A tool `money_summary(month?)` returns code-computed
  numbers (aggregates only): per-category totals for the month and the 3-month average, ratios, counts
  ("delivery: 14 orders"), the top 3 merchants per category with count and total ("Glovo:
  12 orders, 2 340 ₴"), the insight flags, race cost. No single transactions, no dates of
  single purchases, no account ids, no balances, no transfer descriptions.
- Agent context: at most 2 insight flags of the month as short facts, only if the person tracks
  money. The coach links them to goals in words (that's the LLM part): "your goal says cook more;
  delivery is 2.1× your usual".
- Morning report: never money (keeps it a training report). Sunday weekly push: one line
  "Spent on food: 3 200 ₴ (delivery 1 100 ₴)" if tracked.
- **Receipts → food log:** after a grocery, restaurant or café receipt, the coach's reply
  offers "Log as a meal?" with the food lines (a button, like the existing one-tap actions).
  Restaurant/café receipts: one tap logs them as a meal through C3 (the receipt lines are the
  meal description; C3 estimates nutrition as for text). Grocery receipts are *not* a meal
  (food bought ≠ food eaten), so for them the button is "Add to my pantry note" only if a later
  plan adds a pantry; in this plan, groceries are offered only when the receipt is clearly a
  ready-to-eat purchase (single-person sizes, ≤ 5 food lines, e.g. a sandwich and a drink) —
  decided by a code rule on the line categories and count. Sports-nutrition lines (gels, bars)
  are offered as "Log as race/training fuel". Nothing is logged without the tap.
- C9 day review: unchanged (it already sees meals logged from receipts).

### UI

- New page **Money** (`/money`, in the nav only when `money` is tracked; icon to add: `wallet`).
  Mobile-first: month header with ← →; total spent; category bars (sorted, each with the
  3-month average tick); insight cards ("Delivery 2.1× your usual · 14 orders"); race cost
  card if a race is set; transaction list grouped by day with a category chip — tap the chip
  → pick a category → saved as `category_by = 'user'` and, with "Always for this merchant",
  a per-user `merchant_rules` row. "Add receipt" button.
- Settings → "Money": Monobank status ("Connected · 2 cards ·…1234, …5678 · last import 10 min
  ago"), "Disconnect" (deletes token, removes the webhook by setting an empty URL, keeps or
  deletes the transactions — asks), "Delete all money data".

### Setup card and welcome

- `TRACKS` adds `("money", "wallet", "Spending", "Monobank and receipts")` /
  «Витрати», «Monobank і чеки».
- `setup_cards` adds `money` when tracked and no `monobank` secret. Sheet
  `partials/setup_money.html`:
  - EN: "**Connect Monobank (read-only).** The coach sees your card purchases to show where
    money goes. It cannot move money. 1. On a computer (or a second phone), open
    api.monobank.ua. 2. A QR code appears. Open the Monobank app on your phone and scan it
    (in the app: the scanner icon on the main screen). 3. Confirm in the app. 4. The site shows
    your token (a long line of letters). Copy it. 5. Paste it below, choose how many months to
    import (6 is a good start) and press Connect. 6 months of purchases arrive within about
    3 hours. You can revoke the token any time on
    the same site."
  - UA: "**Під'єднайте Monobank (лише читання).** Коуч бачить покупки з картки, щоб показати,
    куди йдуть гроші. Переказувати гроші він не може. 1. На комп'ютері (або другому телефоні)
    відкрийте api.monobank.ua. 2. З'явиться QR-код. Відкрийте застосунок Monobank і
    відскануйте його (значок сканера на головному екрані). 3. Підтвердіть у застосунку. 4. Сайт
    покаже ваш токен (довгий рядок літер). Скопіюйте його. 5. Вставте нижче й натисніть
    «Під'єднати», обравши, за скільки місяців завантажити (6 — добрий початок). Покупки за
    6 місяців з'являться приблизно за 3 години. Відкликати
    токен можна будь-коли на тому ж сайті."
  - Steps 2–4 are checked against the live site at step B4.1 (the docs page only says "scan
    the QR code"); screenshots are not used (they'd show a real account).
  - Receipts without Monobank: the card's second button "I'll just send receipts" marks the
    card done; receipts work for everyone, also without a Monobank card.

### Privacy

- Stored per transaction: Monobank `id`, time, amount and currency, `mcc`/`originalMcc`,
  description (merchant name), hold, category, `category_by`. **Not stored:** `comment`
  (free text the person typed), `counterIban`, `counterEdrpou`, `counterName`, `balance`,
  `receiptId`, the account `iban`, full `maskedPan` (only the last 4), the client `name`.
- P2P transfers: MCC 4829-type rows have the description replaced by "Transfer" before storing
  (descriptions there contain people's names).
- To any LLM: C11 gets merchant descriptions + MCC only (no amounts, dates or accounts), only
  for merchants the rules can't place, never transfer rows. The coach gets aggregates only.
  Receipt photos go to the LLM only when the person sends one.
- Webhook URL contains a random 32-byte `hook_token` (stored hashed, like a password); it is the
  only public route added (an exception in `app/auth.py` next to `/cron/`, documented in
  `docs/design-guidelines.md`). The handler accepts only items whose `account` is one of that
  user's accounts.

### Migration `011_money.sql`

```sql
alter table user_secrets drop constraint user_secrets_provider_check;
alter table user_secrets add constraint user_secrets_provider_check
    check (provider in ('intervals', 'openrouter', 'ical', 'monobank'));

create table money_accounts (
    user_id uuid not null references users on delete cascade,
    account_id text not null,          -- Monobank account id (an API handle, not the IBAN)
    kind text not null,                -- black, white, fop, …
    currency int not null,
    last4 text,
    import_since timestamptz not null, -- how far back the person chose (default 6 months)
    imported_from timestamptz,         -- oldest time imported so far
    synced_until timestamptz,          -- newest time covered by a statement call
    next_at timestamptz not null default now(),
    primary key (user_id, account_id)
);

create table money_hooks (
    hook_hash text primary key,        -- sha256 of the token in the webhook URL
    user_id uuid not null unique references users on delete cascade
);

create table transactions (
    id bigint generated always as identity primary key,
    user_id uuid not null references users on delete cascade,
    source text not null check (source in ('monobank', 'receipt')),
    ext_id text,                        -- Monobank id
    account_id text,
    at timestamptz not null,
    amount_minor bigint not null,       -- negative = spending, in account currency
    currency int not null default 980,
    mcc int,
    original_mcc int,
    description text,
    hold boolean not null default false,
    category text,
    category_by text check (category_by in ('rule', 'llm', 'user', 'receipt')),
    parent_id bigint references transactions on delete cascade,  -- receipt split lines
    unique (user_id, source, ext_id)
);
create index on transactions (user_id, at);

create table merchant_rules (
    user_id uuid not null references users on delete cascade,
    merchant text not null,             -- normalised description
    category text not null,
    by text not null check (by in ('llm', 'user')),
    primary key (user_id, merchant)
);
```

(Receipts are stored as a `transactions` row with `source = 'receipt'` and its lines as children
via `parent_id`; no separate `receipts` table is needed. The image is not kept.)

### Steps

1. Check the live token flow on api.monobank.ua with Oleksii's phone (no data saved) and update
   the sheet text → verify: the steps match the screens.
2. `app/spend_rules.py` (MCC table, merchant rules, normalisation) → verify:
   `tests/test_spend_rules.py`, one case per rule.
3. Synthetic set `evals/make_c11_spend.py` → `evals/data/c11_spend.jsonl`: 150 transactions
   (Ukrainian and international merchant spellings, Cyrillic/Latin mixes, MCC including
   misleading ones, unknown local cafés, race entry sites, sports nutrition shops, pharmacies,
   transfers), labelled by hand (Oleksii checks the labels); 10 synthetic receipts (PIL-drawn,
   UA fiscal-receipt layout imitation, fake shop names) with lines labelled → verify: label
   review done.
4. C11 prompt + `pipeline/spend.py` + `pipeline/receipt.py` → verify: `evals/run_c11.py`.
5. Migration 011; `app/mono.py` (`connect`, `sync_step`, webhook set/unset), tick wiring,
   `POST /money/mono` (connect), `DELETE /money/mono`, `POST /hooks/mono/{token}` (+ GET for
   validation), `POST /money/tx/{id}/category`, `POST /money/receipt`, `GET /money` → verify:
   tests with a fake Monobank (`httpx.MockTransport`): rate-limit respected (never two calls
   per user per tick), 31-day windows, ≥500 handling, hold→settled upsert, webhook unknown
   token 404, foreign account rejected, webhook for user A never writes to user B; isolation
   tests for every route.
6. `app/money_stats.py` insights + `money_summary` tool + agent context → verify:
   `tests/test_money_stats.py` (ratio, thresholds, empty months, race cost window) and a check
   that the tool output has no description/ext_id/account fields (test asserts the keys).
7. Money page, Settings section, setup sheet, welcome track, nav entry, `wallet` icon, i18n →
   verify: `/ui-check` Money page with the demo athlete's synthetic transactions (in
   `app/demo.py`).
8. Report sections (data understanding: Monobank fields and limits, what we drop and why;
   modeling: rules + C11; evaluation: rules-only vs rules+LLM); deploy; set the webhook from
   prod only.

### Evaluation (C11)

`evals/run_c11.py`:

| Metric | Data | Target |
|---|---|---|
| Category accuracy, **rules only** (unplaced = wrong) | 150 synthetic transactions | reported (expect ~0.7) |
| Coverage of rules (share placed) | same | reported |
| Category accuracy, **rules + C11** | same | ≥ 0.90 |
| C11 accuracy on the rule-unplaced subset only | same | ≥ 0.80 |
| Receipt: total exact, line category accuracy, split matches the transaction | 10 synthetic receipts | 10/10, ≥ 0.85, 10/10 |
| Receipt → meal offer: offered when it should be (restaurant/café/ready-to-eat), not for a weekly grocery shop | same 10 + 5 more | ≥ 0.9 accuracy |
| Privacy check: C11 inputs contain no amount/date/account | logged C11 inputs in the run | 0 violations |

The report shows the confusion matrix for the main confusions (eating_out vs delivery,
groceries vs sports_nutrition, gym_classes vs race_entries).

### Acceptance

- [ ] Connect Monobank from the sheet; the chosen period (default 6 months) imported within ~3 h, respecting 1 call /
      60 s; new purchases appear within a minute through the webhook, or within 6 h without it.
- [ ] Money page with categories, insights and corrections at 375/1280, light/dark, EN/UA.
- [ ] Only aggregates reach the coach; the tool-output test proves it; token encrypted; no
      IBAN/comment/counterparty stored.
- [ ] C11 rules-only vs rules+LLM recorded; ≥ 0.90 or the gap explained.

---

## B5. Garmin Personal API (Oleksii's own account, read-only)

### Purpose

Get the Garmin data that intervals.icu does not carry (to be confirmed in step 1; likely
candidates: Body Battery, stress, sleep stages and sleep score details, respiration, training
readiness) straight from Garmin, for Oleksii's own coaching. intervals.icu stays the source for
everything it already provides and the only path for sending workouts to the watch.

### What the API gives (checked 2026‑11‑20)

<https://developer.garmin.com/gc-developer-program/personal/personal-faq/>: the key is created
in Garmin Connect Web (Personal API Key page → Create Key → accept terms → expiry 30/90/180 days
or 1 year → shown once). `POST https://personal.connectapi.garmin.com/personalapitoken-service/
personal-api/personal-api-key/token` with `Authorization: ApiKey <key>` returns an access token
valid 24 h (or until the key expires); no refresh tokens, just ask again. Activity (JSON, .FIT),
Health (JSON), Women's Health (JSON); pull only. The endpoint list is in the "Personal API
Swagger Docs" page (a JS app; read it in the browser at step 1).

### Components

| Component | Kind | Input | Output |
|---|---|---|---|
| `garmin.token(user)` | code | the encrypted personal key | a 24-h access token, kept in memory per process (re-requested on 401 or after 23 h) |
| `garmin.sync(user, days)` (tick, hourly, like `health.maybe_sync`) | code | access token, last synced day | `garmin_daily(day, data jsonb)` rows for the chosen health summaries; first run 30 days back |
| `health.day_snapshot` extension | code | `garmin_daily` + `wellness_daily` | the snapshot gains the extra fields when present (e.g. `body_battery_max`, `stress_avg`); intervals.icu values win where both exist |

### Who can use it

Only accounts in `ADMIN_EMAILS` (i.e. Oleksii) see the "Garmin (personal API)" block in
Settings; the route checks the same. No setup card, no welcome track: this is personal use, not
a feature for family members. Key expiry: a Settings line "Key expires on 12 May" and a push
7 days before (Garmin also e‑mails).

### How the coach uses it

C5 day type and the morning report get the extra fields in the snapshot (`baseline_7d` for each
too, computed in code like HRV today). The C5 prompt gets one line on how to read them (e.g.
"low Body Battery at wake-up + high stress → lean towards recover"). No other component changes.

### Migration `012_garmin.sql`

```sql
alter table user_secrets drop constraint user_secrets_provider_check;
alter table user_secrets add constraint user_secrets_provider_check
    check (provider in ('intervals', 'openrouter', 'ical', 'monobank', 'garmin'));

create table garmin_daily (
    user_id uuid not null references users on delete cascade,
    day date not null,
    data jsonb not null,               -- only the fields we map, not the full response
    synced_at timestamptz not null default now(),
    primary key (user_id, day)
);
```

### Steps

1. Read the Swagger docs in the browser; list endpoints, fields, rate limits; pick the fields
   intervals.icu lacks; record them in `docs/report/02-data-understanding.md` → verify: a
   one-off script with Oleksii's key (run locally, output not saved in git) prints one day.
2. Migration 012; `app/garmin.py` (`token`, `sync`, field mapping) → verify: tests with
   `httpx.MockTransport` and synthetic JSON fixtures (token reuse, 401 → new token, expired key
   → clear error, missing fields).
3. Settings block (admin only) + `POST /settings/garmin`, `DELETE /settings/garmin` → verify:
   non-admin gets 403/404; isolation test.
4. Snapshot + C5 prompt line → verify: `/eval c5` not lower (C5 cases get the new fields as
   optional).
5. Report note; deploy.

### Evaluation

The sync is a data component: metric = field-mapping tests pass (100 %) on synthetic fixtures,
plus an agreement check on overlapping fields (resting HR, HRV, sleep hours) between Garmin and
intervals.icu over Oleksii's last 30 days, run locally; only the agreement numbers (e.g. "RHR
equal on 29/30 days") go into the report, never the data.

### Acceptance

- [ ] Oleksii's Settings shows the Garmin block; nobody else's does.
- [ ] Extra fields appear in the Health page snapshot and in C5 inputs; C5 eval not lower.
- [ ] Key encrypted, never logged; expiry reminder works.

---

## Order of work inside each slice

migration → components (code first, then LLM) → eval set + eval script + result → routes with
isolation tests → sync in the tick → UI + setup card + welcome track + i18n → `/ui-check` →
report section → deploy → short demo-script addition.

## Evaluation summary

| Component | Kind | Metric | Data | Target |
|---|---|---|---|---|
| C12 Weather advice (B1) | code | rule-case pass rate | 40+ hand-written cases | 100 % |
| C13 Day windows + C6 (B2) | code + LLM | overlaps with busy blocks; fit rate; sleep-warning recall | 15 synthetic days | 0; ≥ 0.9; 1.0 |
| C10 Lab extraction (B3) | LLM + code | marker F1; value exact; unit+range exact; flag accuracy; leaks | 15 synthetic sheets (PNG, photo-like, PDF) | ≥ 0.9; ≥ 0.95; ≥ 0.9; ≥ 0.95; 0 |
| C11 Spend category (B4) | rules + LLM | accuracy rules-only vs rules+C11; receipt totals/lines | 150 synthetic transactions, 10 receipts | ≥ 0.9 with C11 |
| Garmin sync (B5) | code | mapping tests; agreement with intervals.icu | synthetic fixtures; own data locally | 100 %; reported |
| C6, C7, C9 (existing) | — | existing metrics must not drop; + new cases | existing + new cases | no drop |

Each new eval is a `evals/run_cNN.py` registered in `evals/run_all.py`, writing
`evals/results/cNN_*.json`, and summarised in `docs/report/05-evaluation.md` with an
explanation of misses.

## Tests (all slices)

- Two-user isolation for every new route: `/location`, `/settings/location-auto`,
  `/settings/training-time`, `/calendar` (POST/DELETE), `/calendar/titles`, `/labs*`,
  `/money*`, `/settings/garmin`, plus the webhook (user A's token cannot write to user B's accounts).
- `test_routes_protected` (existing) must pass with the one new public prefix `/hooks/mono/`.
- Secrets: ICS URL and Monobank token never appear in logs (caplog test) or in LLM inputs
  (assert on the traced inputs in the eval runs).
- Tick: a test that the tick with no new sources behaves exactly as before.

## Acceptance criteria (whole plan)

- [ ] Each slice has a setup card with EN/UA steps, a welcome "what to track" option, a sync in
      the cron tick where needed, an eval with a recorded result, a report section, and is
      deployed.
- [ ] Only aggregates of money data (category totals, top merchants) reach the coach LLM; C11
      sees merchant names + MCC only;
      tokens and the ICS URL encrypted; two-user isolation tests for every new endpoint.
- [ ] `/ui-check` at 375/1280, light/dark, EN/UA for every changed page; `i18n_check` 0 missing.
- [ ] Hosting stays free: request-based Cloud Run, no min instances, no new scheduler job, no
      paid API.

## Decisions (Oleksii, 2026‑11‑20)

1. Order B1 → B2 → B3 → B4 kept; B5 (Garmin, own account) after B4, or earlier if convenient —
   it is independent.
2. Calendar: busy-only by default, opt-in toggle to show event names to the coach.
3. Location: silent update on app open when permission is granted and the location is > 6 h
   old; default on, toggle in Settings.
4. Unknown merchant names (no amounts/dates/accounts) may go to C11, and the coach may see the
   top 3 merchants per category.
5. Lab photos/PDFs stay only in the chat (as chat attachments); no separate file storage.
6. Garmin Personal API for Oleksii's own account only (B5); intervals.icu for everyone else and
   for workouts to the watch; no Business application.
7. Monobank first import: the person chooses 1/3/6/12 months; default 6.
8. Receipts → food log: yes, offered with one tap (restaurant/café/ready-to-eat and sports
   fuel; not a weekly grocery shop).
9. PrivatBank dropped entirely; Monobank + receipts only.
10. Usual training time, wake time and bedtime are set in Settings only (defaults 07:00 /
    07:00 / 22:30).
