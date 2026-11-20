# 04 — Modeling

CRISP-DM phase 4. The system is a set of small, separately evaluated LLM components plus
code. It is not one big prompt and not RAG.

> **Read this first.** The table below and the next sections describe **v2** (a fixed pipeline
> with a router). Since v3 the components are tools of one coach agent, and C1 is scored as tool
> routing. The current component table, diagram and one-input walk-through are in the
> [report README](README.md). The v3 to v5 sections further down say what changed and why.

## Components (v2, kept for history)

| | Purpose | Input → output | Model | Why this model |
|---|---|---|---|---|
| C7 | Safety gate | message → `{red_flag, category, reason}` | 3.1 Flash-Lite | Simple, high-recall classification; runs every turn |
| C1 | Router | message + last 4 turns → intents ⊆ {log, question, plan, profile, chitchat} | 3.1 Flash-Lite | Multi-label classification |
| C2 | Log extractor | message + local time → events[] + facts[] | 3.1 Flash-Lite | Information extraction, temporal normalisation, UA/EN |
| C3 | Nutrition | meal text → items with grams, kcal, macros | 3.1 Flash-Lite | Totals are recomputed in code |
| C0 | Interviewer | known profile + facts + slot list → filled slots + ≤ 2 questions | 3.8 Flash | Slot-filling dialogue; needs reasoning to avoid redundant questions |
| C5 | Day type | wellness vs baseline + logs + facts → recover/easy/normal/push + evidence | 3.8 Flash | Reasoning over mixed signals |
| C6 | Planner | day type, plan, history, profile, request → structured workout | 3.8 Flash | Structured generation under constraints |
| — | Validator | workout → violations[] | code | Hard rules are never left to the LLM |
| C4 | Sources | file → chunks (1,400 chars, paragraph-aware, 250 overlap) → embeddings (gemini-embedding-2, 768 d, pgvector HNSW) + proposed facts with quotes (user confirms); query → top-k excerpts | 3.1 Flash-Lite + embeddings | Long personal history (ChatGPT exports) is too big for a prompt; retrieval brings only the relevant parts. Facts make the important parts permanent and editable |
| C8 | Reply | this turn's results + context → short reply | 3.1 Flash-Lite | Grounded generation |

## Design decisions

- **Structured output everywhere.** Each component has a Pydantic schema sent as a JSON
  schema. Invalid output gets one retry, then a clear error.
- **Reasoning budget.** Gemini 3.8 Flash runs with `reasoning: low`, and its output limit is
  raised. The first end-to-end test failed because reasoning tokens used up `max_tokens`. A
  reply cut off by the limit is retried with more room.
- **Code where code is enough.**
  - baselines and the 7-day means;
  - meal totals;
  - the workout validator (duration, zones, injury, red flag, a main set is required);
  - rendering to intervals.icu workout text (`- 10m Z1-Z2 HR`, `5x`, `- 400mtr Z4 Pace`). This
    format was verified by creating real events and reading back the parsed steps.
- **Parallel calls.** C7 and C1 run in parallel. A full turn takes ~10–18 s; a log-only turn
  is faster.
- **Human in the loop.** Nothing is written to intervals.icu until the user presses **Send to watch**;
  **Undo** deletes the event.
- **Prompts.** One Markdown file per component in `app/prompts/`.
- **Tracing.** Langfuse traces every turn (`handle-chat-turn`), with one generation per
  component, user and session (user + day), model, tokens and cost.
- **Cost.** About $0.002–0.007 per full turn, measured in Langfuse. There is a $5/month cap per
  user, checked before every call.
- **Memory has three layers:**
  1. facts (confirmed, editable, always in context);
  2. a 14-day digest of past days, built in code from the logs, assessments and sessions, so it
     can't drift from what happened. The History calendar shows the same data;
  3. file excerpts found by similarity search, only when the turn needs them (question or plan).
- **File processing.** Files are processed step by step. Each request handles 24 chunks (3
  parallel LLM calls), and the page polls the next step, so a 5 MB export is read without
  background workers on Cloud Run.
- **Setup is a form flow, not a chat.** Research (see plan 04) found chat-based onboarding helps
  only when the chat actually does the setup work. Our setup needs specific inputs, so it is a
  short form flow (5 steps since v4). C0 runs in the last step and asks ≤ 5 questions about what is still missing after
  intervals.icu, the form and the files.
- **Voice input.** The browser records audio and the server sends it to a speech-capable model
  (Gemini Flash-Lite via OpenRouter), which returns the text into the message box; you check it
  before sending. v2 used the browser's Web Speech API; since v3 one server-side path handles
  every browser and keeps Ukrainian, English and mixed speech as spoken (webm, mp4 and wav
  tested). Not evaluated with a metric (see 05-evaluation, "Not evaluated").

## Main alternative considered

One agent with tools (read wellness, write logs, create workout) instead of a fixed pipeline. It
lost because:
- it is harder to evaluate per component;
- it is harder to guarantee "no write without Send to watch";
- cost and latency are less predictable.

## v3 (2026-11-14, late): from a fixed pipeline to an agent

**What changed:** after using v2, the athlete wanted the app to act for him: log, add gear,
create reminders, read a Garmin plan screenshot, plan the week. So the fixed pipeline became one
**tool-using agent** (`app/agent.py`). The components are its tools:

| Before | Now |
|---|---|
| C1 router picks steps | The agent picks tools (C1 eval re-scored as tool routing) |
| C8 reply writer | The agent's final answer (C8 eval re-run on the agent, without tools) |
| C2 → C3 → logs | Tool `log_entries` (C3 now also for drinks: caffeine, sugar, alcohol; 16 nutrients) |
| C5, C6 + validator | Tools `assess_day`, `plan_sessions` (several days, for week planning) |
| C4 search | Tool `search_memory`; files are still read into facts for review |
| — | `save_item`/`end_item` (long-term or until a date), `set_reminder`, `update_profile`, `set_planned_workouts` (vision), `nutrition_summary`, `health_summary` |

**Design rules kept:**
- every write is recorded with an undo recipe and shown as a line with **Undo**;
- the watch is only written after **Send to watch**;
- the safety gate (C7) runs in parallel and is passed into the agent's context;
- at most 6 tool steps per message;
- a monthly cap per user, unless the user adds their own OpenRouter key.

**Models:**
- Gemini 3.8 Flash for the agent (tools, images, audio; cached input $0.08/M);
- Claude Sonnet 5.5 for "Think harder";
- Flash-Lite for extraction and voice transcription.

A message with tools costs about $0.008–0.02 and takes ~15–25 s.

**Main alternative:** keep the fixed pipeline and add more steps. It lost because the athlete's
requests (gear, reminders, screenshots, week plans) are open-ended; a fixed pipeline would need a
new branch for each one.

## v4 (2026-11-15): clarity and code-only components

A usability review of v3 (by the athlete) found the app worked but was hard to read. v4
(plan 06) changed the interface and added small components. Most are **code, not LLM**,
because the answer is a calculation, and a calculation shouldn't be made up:

| Component | Input → output | How |
|---|---|---|
| Patterns | 90 days of logs + wellness → "after alcohol your next-morning HRV is 15% lower (10 nights vs 50)" | Compare next-morning HRV, resting HR and sleep after tagged days (alcohol, a meal after 21:00, > 300 mg caffeine, < 6.5 h sleep) with other days; shown only with ≥ 5 vs ≥ 10 nights, ≥ 5% difference and Welch t ≥ 2.5 (v6; was 3 vs 5 nights and 5%, which fired on random data) (`app/patterns.py`) |
| Pain trend | pain logs (C2 already extracts body part and 0–10) → per body part: points, latest, 7-day vs previous 7-day trend | `health.pain_trend` |
| Session fuel | planned workout + weight → before / during / after | Sports-nutrition rules of thumb: 1–2 g/kg carbs before long sessions, 30–60 g/h during sessions over 75 min (60–90 g/h over 150 min), 1 g/kg carbs + 0.3 g/kg protein after hard or long ones; carb target ≥ 7 g/kg on a day with a 90+ min session |
| Shoe km | gear items + runs from intervals.icu → km per shoe, "replace soon" at 85% of 600 km | Runs with a gear name go to the matching shoe; others to the newest shoe |
| Weather | city (Settings) → forecast and EU air quality for the planned day | Open-Meteo (no key); passed to the C6 planner, whose prompt says how to adapt (heat, poor air, rain, frost) |
| Week review | activities, wellness, logs → this week vs last | Code; a Sunday push |

**The agent changed in four places:**
- photo meals are listed with grams and confirmed before logging;
- no assumption that the athlete uses Garmin Coach: the plan can come from a screenshot, the
  intervals.icu calendar (synced hourly) or nowhere;
- `update_profile` takes only a fixed list of keys;
- file search results are wrapped as untrusted text.

The last two are prompt-injection defences: a file can't rewrite the coach's instructions,
and its text is marked as data.


## v7 (2026-11-20): family-ready (plan 10)

- **Chat turns run in the background.** Before, `POST /chat` ran the agent inside the request,
  in an `async` handler, so for 5–30 s the whole server process was blocked: opening another
  page hung or failed. Now the request saves the message and a `chat_turns` row, starts the
  agent in a small thread pool and returns a "Coach is replying…" bubble that asks
  `GET /chat/turns/{id}` every 1.5 s. Today shows a running turn again after you come back. A
  turn older than 3 minutes is marked failed. Alternative: streaming (SSE). It lost because it
  does not survive leaving the page.
- **Photo meals are logged at once** (no "Right?"). The reply lists what was logged and says
  how to correct it. A correction calls `log_entries` with `replaces_last: true`, which undoes
  the previous entry first, so nothing is counted twice.
- **C9 Day review (new LLM component).** Purpose: explain one day's eating on the Nutrition
  page. Input: that day's totals, targets for its day type, meals with times, drinks, training,
  plus `analysis` computed in code (status per target, limits, issues ranked worst first).
  Output: `DayReview {good, short, tip}` (Pydantic), in the UI language. Model: Gemini 3.1
  Flash-Lite. It is cached per day and language until the day's numbers change (`day_reviews`,
  keyed by a hash of the input). The comparisons moved to code after the first eval run (see
  05).
- **Per-person AI access.** `llm.check_budget` reads `users.ai_access` and the monthly cap:
  the per-person `monthly_cap_usd`, else $20 for the invite list and admins, else $1 for
  newcomers. The app key comes from `users.key_pool` (`main` or an optional `family` key). A
  person's own key still wins.

## B2 (2026-11-20): calendar and C13 Day windows (plan 11)

| Component | Kind | Input | Output |
|---|---|---|---|
| `calendar.fetch` / `parse` / `sync` (`app/calendar.py`) | code | encrypted ICS link | busy blocks (UTC) for −1…+14 days in `calendar_blocks` |
| **C13 Day windows** (`app/day_windows.py`) | code | the day's blocks, wake/bed time (default 07:00–22:30), sleep target (8 h) | busy and free windows (30-min buffers, 60 min before the first event), longest free window, latest bedtime, sleep possible before tomorrow's first event, warnings |
| C6 planner + validator | LLM + code | as before + `day_windows` | a workout with `start: "HH:MM"`; the validator rejects a start that does not fit inside one free window and the existing 2-attempt loop re-plans |

Decisions:

- **Code for time, LLM for choice.** C13 does all time arithmetic. The LLM only picks a window
  and the session. The validator is the hard guarantee: a proposal that overlaps busy time is
  never shown.
- **Library over a hand-written parser** for ICS: recurring events, overrides and DST are where
  a hand parser goes silently wrong.
- **Sync only in the tick** (`calendar_feeds.next_at`, 30 min, 2 h after an error), plus one
  background sync right after the person presses Connect. Page renders never fetch.
- **The coach** gets a short busy summary for today and tomorrow and the C13 warnings. Event
  names appear only with the opt-in toggle. The evening nudge says "Early start tomorrow (07:00):
  aim to be in bed by 22:30" when the calendar leaves less sleep than the target.
- **Wake/bed/training time** come from B1's Settings fields (migration 008). Until B1 is merged,
  `day_windows.prefs_times` reads them defensively and falls back to 07:00 / 22:30 / 07:00.
## B3 (2026-11-20): lab results, C10 lab extraction (plan 11)

**Purpose.** Keep blood tests in one place with trends and reference ranges, and let the coach
connect them to training and food. Input: a phone photo of the lab sheet or the lab's PDF.
Output: one row per marker (value, unit, range, low/high flag, test date) in `lab_results`.

**Split, as in C9: the model copies, code decides.**

| Step | Kind | What it does |
|---|---|---|
| `labs.read_file` | code | photo → JPEG ≤ 2000 px (Pillow); PDF → text (`pypdf`); a PDF without a text layer → "send a photo instead" (no OCR stack) |
| **C10** `pipeline/labs.extract` + `prompts/c10_labs.md` | LLM (vision), Flash-Lite; Flash once if the JSON fails | `LabSheet{lab, taken_on, rows[name, value, unit, ref — all *as printed*]}`. No field for patient name, birth date, order number or doctor |
| `labs.normalise` + `app/lab_catalog.py` | code | 38 markers with EN/UA/RU names; parses `12,4`, `<0.5`, `5,6 ↑`, ranges `30 - 100`, `до 15`, `< 5`; converts units (vitamin D ng/mL × 2.496, glucose mg/dL ÷ 18, Hb g/dL × 10, …); flag uses the **lab's printed range first**, the catalogue default only when none is printed |
| `labs.trend`, `context_lines`, `low_flags` | code | trends for the Health page and the `lab_results` tool; the short list the coach sees |

**What the coach sees.** Only a short list, computed in code: the latest out-of-range value of
each marker from the last 12 months plus the latest ferritin, vitamin D and haemoglobin
(`"Ferritin 18 µg/L (2026-09-12, range 30–400): low"`). It goes into the agent context, into
C5/C6 `facts` (as context, never a medical decision), and C9 gets `lab_flags` (low ferritin /
haemoglobin → the tip may name iron-rich foods, never tablets or milligrams). Two new tools:
`read_lab_sheet` (a lab photo sent in the chat) and `lab_results(marker?)`.

**Where the original lives.** Every upload is a chat message (photo thumbnail or a PDF chip)
and the coach's reply is the extracted list with an Undo. No separate file storage
(decision 5 in plan 11). The image goes to the LLM only on that explicit upload; Settings → Your
data says so and has "Delete all lab results".

**Prompt change from the eval.** The first C7 lab-reply run showed the coach saying a high TSH
"points to hypothyroidism" and once giving no training advice. The coach prompt now says: name
the value as below/above the lab's range, suggest a doctor, never name a condition or a dose,
and always add one or two training-safe tips.
## B4 (2026-11-20): money — rules first, C11 for the rest (plan 11)

- **Code for numbers, LLM for language.** `app/spend_rules.py` places a payment by sign/type
  (income, transfers, cash), then merchant-name rules on a normalised name (lowercase,
  Cyrillic transliterated, punctuation dropped, so "СІЛЬПО" = "Silpo"), then an MCC table.
  A person's corrections become per-user `merchant_rules` and win over the built-in rules.
  A payment within 120 days before a race fact to a merchant named like the race →
  `race_entries` (code).
- **C11** (`app/pipeline/spend.py`, prompt `c11_spend.md`, Flash-Lite): only the merchants the
  rules can't place, de-duplicated, ≤ 30 per call, **merchant name + MCC only** (no amounts,
  dates, accounts, never transfers). The answer is cached per user in `merchant_rules`, so a
  merchant is asked about once.
- **Receipts** (`app/pipeline/receipt.py`, prompt `c11_receipt.md`, vision): the LLM only reads
  the photo into `Receipt{store, date, total, kind, lines}`. Code sets each line's category
  (product keywords, else the receipt kind's default), adds a remainder line so lines add up to
  the total, matches the receipt to a card payment (same day ±1, total within 1 ₴) and splits it,
  and decides the meal offer (restaurant/café, a small ready-to-eat purchase, or sports fuel;
  never a weekly grocery shop). Nothing is logged without the person's tap.
  *Deviation from the plan:* receipt lines don't go to C11; the kind default was enough on the
  eval set and saves a call.
- **Insights** (`app/money_stats.py`, code): per category this month so far vs the same days of
  the previous 3 months with data; flag at ratio ≥ 1.5 and ≥ 500 ₴ difference (or ≤ 0.5);
  top 3 merchants; race cost since the race was added. The coach gets this only through the
  `money_summary` tool and at most 2 flags in its context — aggregates only (a test asserts the
  keys).
- **Sync:** `mono.sync_step` in the 15-minute tick makes at most one Monobank call per user per
  tick (backfill: the oldest missing 31-day window; then a catch-up every 6 h); the public
  webhook `/hooks/mono/{token}` does one lookup and one insert. Free hosting unchanged: no new
  scheduler job, no min instances.
## B1 (2026-11-20, plan 11): location and C12 weather advice

**Purpose.** Plan around the real conditions where the person is, at the hour they train.

| Component | Kind | Input | Output |
|---|---|---|---|
| `POST /location` | code | lat/lon from the browser | profile `location = {name, lat, lon, source: gps, at}`, rounded to ~1 km |
| `weather.forecast` / `reverse_name` | code (Open-Meteo, Nominatim) | rounded point | hourly + daily forecast, AQI, pollen; place name |
| `weather.session` | code | place, day, usual training time (Settings), session length, sport | the session hours, the day, hourly strip, C12 advice |
| **C12** `app/weather_rules.py` | code (rule tables) | session hours, 12 h before, sunrise/sunset | `pace_slower_pct`, `heat_level`, `clothing`, `flags`, `best_hour`, `facts` |

**C12 rule tables** (heuristics, documented as such, tuned by Oleksii, not a study):

1. Heat → pace: air temperature + dew point in °F, the common runners' table (≤ 100 → 0 %, …,
   171–180 → 8–10 %, > 180 → no hard running). Cycling gets "drink more, ride by HR" instead.
2. Clothing by the coldest feels-like during the session, bands at 20 / 12 / 5 / 0 / −5 °C, plus
   windproof layer at gusts ≥ 30 km/h, rain jacket at rain probability ≥ 60 %, sunscreen at
   UV ≥ 6 when warm.
3. Flags: `indoors_aqi` (European AQI > 80), `storm` (codes 95/96/99), `rain` (≥ 4 mm/h),
   `ice` (≤ 0.5 °C and freezing-rain codes, or wet with temperature crossing 0 °C in the last
   12 h), `dark` (session starts before sunrise or ends after sunset), `uv_high` (UV ≥ 6), `wind`
   (gusts ≥ 50 km/h), `pollen` (CAMS "high" band, only when a profile fact mentions an allergy).
   AQI 60–80 adds the fact "shorten the intervals".
4. Best hour: the daylight start hour with no flags and the lowest heat sum.

**Why code, not the LLM:** these are thresholds on numbers; code is exact, free, testable and
explains itself. The LLM only reads the `facts` (C6 planner, chat, morning report) and puts them
into words.

**How the coach uses it.** C6 gets `weather = {day, session_hours, advice}` and a hard rule:
with `indoors_aqi` or `storm`, an outdoor sport may only use zones 1–3. The validator enforces
it in code (zone 4+ outdoors → feedback, re-plan). The chat context gets `weather_today` (the
C12 facts), so "what should I wear?" is answered from facts. The morning report gets the same.

**Privacy.** Only rounded coordinates leave the server; the planner and chat never see
coordinates, only the place name and the facts.

**Main alternative considered:** show "near 50.45, 30.52" without Nominatim. Rejected: family
members won't read coordinates. Another: let the LLM decide clothing from raw forecast numbers;
rejected for the reasons above.
