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

## B2 calendar: iCal (ICS) links (2026-11-20, plan 11)

- **Source.** A read-only iCal link the person copies from Google ("Secret address in iCal
  format"), iCloud ("Public Calendar") or Outlook ("Publish a calendar", busy-only possible).
  One GET per person every 30 minutes in the cron tick. Free, no OAuth and no Google app review.
- **Format.** RFC 5545. Real feeds contain recurring events (`RRULE` with `EXDATE`), moved single
  occurrences (`RECURRENCE-ID`), `VTIMEZONE` blocks, Google's `X-WR-TIMEZONE` with UTC times,
  floating times, all-day events with an exclusive `DTEND`, cancelled and "show as free" events.
  These are parsed by `icalendar` 7.3 + `recurring-ical-events` 3.8 (BSD-2 / LGPL-3.0, used as
  unmodified dependencies), not by hand.
- **Quality limits.** Google's secret address can lag behind edits (not documented), so the UI
  says "Changes show within about an hour". The feed does not say reliably which attendee is the
  owner, so declined invitations still count as busy. Events longer than 16 h and all-day events
  are day notes, not busy time.
- **Privacy choice.** The link is a credential: stored encrypted (Fernet) in `user_secrets`, shown
  as host + last 4 characters, never logged (only the host), never sent to an LLM. Only start,
  end and all-day are stored, for −1…+14 days, and they are replaced on every sync. Titles are
  stored only if the person turns on "Show event names to the coach" (default off). Locations,
  attendees and descriptions are never stored.
- **Test data.** No real calendar is used: unit tests use hand-written ICS fixtures in
  `tests/data/ics/`, and the test account reads synthetic Google/iCloud/Outlook-style feeds
  generated in memory by `app/demo.py` (`https://calendar.demo.invalid/{google,icloud,outlook}.ics`).
## Money: Monobank personal API (plan 11 B4, checked 2026-11-20, spec v250818)

- **Source:** a personal read-only token from api.monobank.ua (QR scan in the Monobank app).
  The docs allow a personal token for a service used by one's own family.
- **Calls and limits:** `client-info` and `statement/{account}/{from}/{to}` each allow 1 request
  per 60 s; a statement window is at most 31 days + 1 hour (2 682 000 s). The current spec
  states no row cap; older versions returned at most 500 items newest-first, so ≥ 500 items
  are treated as "maybe cut" and the next call continues from the oldest item.
- **Webhook:** Monobank checks the URL with a GET (needs 200), then POSTs each new item; it
  waits 5 s, retries after 60 s and 600 s, then switches the webhook off. So the webhook is an
  optimisation and a 6-hourly catch-up statement call is the source of truth.
- **Fields kept:** id, time, amount (kopecks, negative = spending), currency, `mcc` /
  `originalMcc`, description (merchant), hold; from accounts: id, type, currency, last 4 card
  digits. **Dropped on purpose:** `comment` (free text), `counterIban/Edrpou/Name`, `balance`,
  `receiptId`, IBAN, full card number, the client's name. Transfer descriptions (MCC 4829 type)
  contain people's names and are replaced by "Transfer" before storing.
- **MCC reference:** ISO 18245 via github.com/greggles/mcc-codes (Unlicense); only the ~60
  codes our categories need are kept, in `app/spend_rules.py`.
- **Size:** ~1–2 k rows per person per year (~200 B each), far inside the Neon free 1 GB.
- **Eval data:** no real bank data exists in git. The C11 set is synthetic (see 03).
## B1 (plan 11): location and weather data

| Source | What we read | Limits and licence (checked 2026-11-20) |
|---|---|---|
| Browser geolocation | latitude, longitude, only after the person presses "Use my location", or on app open when the browser already allows it and the stored place is > 6 h old | Rounded to 2 decimals (~1 km) on the server; one current place, overwritten, no history |
| Open-Meteo Forecast API | 7 days hourly: temperature, feels-like, dew point, humidity, precipitation and its probability, weather code, wind and gusts, UV index, day/night; daily: max/min, rain sum, max wind, sunrise, sunset, daylight, max UV; place time zone | Free for non-commercial use, < 10 000 calls/day; 11 hourly variables count as 2 calls; CC BY 4.0, attribution shown in Settings. Cached 1 h per rounded point |
| Open-Meteo Air Quality API (CAMS) | hourly European AQI, PM2.5, birch and grass pollen (Europe only, ~4 days) | Same terms; 5 days ahead |
| Nominatim (OpenStreetMap) | place name for the rounded point (`zoom=10`, city/town level), in the app language | OSMF policy: ≤ 1 request/s, identifying User-Agent (`DailyCoach/1.0 (+app URL)`, no personal email), results cached. One call per button press |

Quality notes: Open-Meteo returns local-time hours with `timezone=auto`, so the session hour is
matched in the place's own time. Pollen is `null` outside Europe and after ~4 days; AQI after
5 days. Every missing value is treated as "no data" by the rules (no flag), never as zero risk
made up by a model. Nominatim at city zoom sometimes returns a municipality name (e.g.
"Бучанська міська громада" instead of "Буча"); acceptable for a label.
