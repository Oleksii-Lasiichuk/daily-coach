# Plan 11 — Life data: location, calendar, labs, money (later)

CRISP-DM phases: 1. Business understanding, 2. Data understanding (new sources),
4. Modeling (C10 lab extraction, C11 spend category), 5. Evaluation, 6. Deployment.
Status: documented for later. Starts after [plan 10](10-v7-life-os.md) (family-ready app) is
deployed and used for a while.

## Goal

Connect the rest of life to the coach so it can reason across areas: money (Monobank,
receipts), calendar, location and weather, lab results. Each source feeds the same coach and
the same day view, so it can say "you spent 2× more on delivery this month although you planned
to cook", "you have 6 h of meetings today, move the long run to Saturday" or "ferritin was low
in September, iron matters on hard weeks".

## Scope

- In: phone location + richer weather with heat/cold/AQI advice; calendar through an iCal link;
  lab results from photo/PDF with trends; Monobank personal API; receipt photos; spending
  insights. Each with a setup card (instructions in EN and UA), a sync in the cron tick, an eval
  and a report section.
- Out: PrivatBank API (no personal API for individuals, only for business accounts; statement
  CSV upload instead, later); route suggestions (needs map data, a separate project); Google
  Calendar OAuth (iCal link first); native app / background location.

## Open questions

1. **Garmin API.** The official Garmin Connect Developer Program is for companies and needs
   approval (weeks, maybe a refusal for a personal project). Unofficial libraries need the
   user's Garmin password stored on our server, which breaks Garmin's terms and is a risk with
   family accounts. Suggestion: keep intervals.icu as the Garmin bridge and apply to Garmin's
   program in parallel.
2. Order: weather/location → calendar → labs → money. Money earlier?
3. Calendar privacy: keep event titles ("dentist at 18:00") or store only busy/free?

## Design

### B1. Location and weather

- "Use my location" button (browser geolocation, only when the app is open; no background
  tracking). Coordinates rounded to ~1 km, stored as the current place; city name by reverse
  geocoding. Fallback: city typed in Settings (exists).
- Weather extended (Open-Meteo, free): hourly temperature, feels-like, wind, humidity, rain,
  UV, European AQI, sunrise/sunset/daylight.
- Code, not LLM: heat/cold rules → pace adjustment (dew point based table), clothing suggestion
  by feels-like temperature and wind, "move intervals indoors" when AQI > 80, rain, ice or
  dark during the planned time. The coach and C6 planner get these as facts.
- Eval: unit tests on the rule tables (known inputs → known advice); no LLM.

### B2. Calendar

- Paste an iCal (ICS) link (Google secret address or iCloud public link): read-only, no OAuth,
  works for both. Synced in the cron tick (every 30 min), stored as busy blocks for −1…+14 days
  (titles kept only if the user allows; default "Busy").
- Code: free windows per day, earliest possible bedtime vs sleep target, "late meeting
  tomorrow 07:00 → sleep by 23:00". The planner C6 gets free windows and moves or shortens
  sessions; it warns when a day has no slot.
- Eval: C6 cases with calendar windows (session fits in a free window, never overlaps a busy
  block); unit tests for ICS parsing (recurring events, all-day, time zones).
- Later: Google OAuth for real-time push (needs Google app review for many users).

### B3. Lab results

- Upload a photo or PDF of a lab report (Synevo, Dila, CSD formats are common in Ukraine).
- New component **C10 Lab extraction** (vision LLM): input image/PDF text; output list of
  `{marker, value, unit, ref_low, ref_high, date, lab}`; markers mapped to a fixed list
  (ferritin, vitamin D, haemoglobin, CBC items, TSH, testosterone, B12, glucose…). Saved
  without a confirmation step, like meals, with an edit table; unknown markers kept as-is.
- Health page: "Lab tests" section with a trend sparkline per marker, last value, reference
  band, out-of-range badge.
- The coach gets recent out-of-range markers as context and must say it is not a doctor
  (C7 safety covers medical claims).
- Eval: 15 synthetic lab sheets (rendered from templates in UA and EN, fake values) with labels;
  metric: marker-level F1 and value exact-match; target F1 ≥ 0.9.

### B4. Money (Monobank + receipts)

- Monobank personal API: user pastes their token; `client-info` lists accounts; statement for
  the last 31 days (rate limit: 1 request per 60 s, so a slow first import in the cron tick);
  then a webhook for new transactions. Token encrypted like other keys.
- Categories in code first from MCC codes (restaurants, groceries, delivery, pharmacy, sport
  shops, medical, transport) + merchant name rules (Glovo, Bolt Food, Silpo, Novus,
  Decathlon, race-registration sites). LLM only for what rules can't place.
- New component **C11 Spend category** (LLM fallback; input: merchant, MCC, amount; output:
  category from a fixed list). Receipt photo → same C11 on the receipt lines (food items can
  also go to the food log if the user wants).
- Insights in code: this month vs average by category; "delivery vs your plan to cook"; race
  preparation cost (race entries + gear + sports nutrition since the race was added).
- Privacy: only aggregates and category totals go to the coach LLM, never raw statement rows.
  No account numbers stored beyond last 4.
- Eval: 100 synthetic transactions (Ukrainian merchant names, MCC) labeled by hand; metric:
  category accuracy, rules alone vs rules + C11; target ≥ 0.9.

## Steps

Each source in order B1 → B4: migration → component → eval → setup card with instructions
(EN/UA) → sync in `/cron/tick` → `/ui-check` → report section → deploy.

## Evaluation

| Component | Metric | Data | Good |
|---|---|---|---|
| Weather rules (B1) | rule tests | table of cases | all pass |
| Calendar (B2) | sessions overlapping busy blocks | 15 C6 cases | 0 |
| C10 Labs | marker F1, value exact | 15 synthetic sheets | ≥ 0.9 |
| C11 Spend | category accuracy, rules alone vs rules + C11 | 100 synthetic transactions | ≥ 0.9 |

## Acceptance criteria

- [ ] Each source has a setup card, a sync in the cron tick, an eval with a recorded result,
      and a report section.
- [ ] Only aggregates of money data reach the LLM; tokens encrypted; two-user isolation tests
      for every new endpoint.
- [ ] `/ui-check` at 375/1280, light/dark, EN/UA for every changed page.
