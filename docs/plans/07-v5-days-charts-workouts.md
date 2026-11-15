# Plan 07 — v5: real workouts, day-by-day data, interactive charts

CRISP-DM phase: 6. Deployment (UI), 4. Modeling (planner cues, morning report, duplicates).
Status: requested by Oleksii on 2026-11-15 after using v4.

## Goal
Make the app something you explore, not read: click anything to see and change it, look at
any day with its Garmin numbers, chart a year of data like intervals.icu, and get workouts
with actual exercises that go to the watch as they are.

## Decisions
| Topic | Decision |
|---|---|
| Workout | Each step has a `cue` (what exactly to do; strength: one step per exercise with sets × reps). The card shows a zone profile bar, a timeline of steps with bpm ranges from your zones, repeats grouped, and a "Watch workout" badge. The cue goes to the watch as the step text (numbers removed so intervals.icu doesn't misread them) |
| Days | `/day/{date}` is the day view: day type with reasons, your Garmin numbers vs your usual (7 days before), a chart three weeks around the day, sessions, log (tap to fix), add entries. Arrows to the previous and next day; reachable from Today, Training's week, Journal and charts |
| Charts | uPlot (MIT, 50 KB, vendored). Health has two charts with any two metrics each, a 7-day average, ranges from 30 days to all, drag to zoom, double-click to reset, synced cursors, exact values, click to pin a day. The weight goal is a dashed line |
| Data | More daily fields from intervals.icu (sleep score and quality, sleeping HR, stress, readiness, SpO2, respiration, body fat); one full re-sync. Minute-by-minute Garmin data isn't available through intervals.icu |
| Details | A shared sheet (`<dialog>`) for items and log entries: every field editable, where it came from (file + quote, or the chat day), end or delete |
| Duplicates | Code blocks near-duplicates on save (word overlap). "Find duplicates" asks the model to group the rest; you confirm each merge |
| Goals | Races and goals first on Training: countdown, target, build-up progress, fitness trend, weight progress. Gear as cards with type and km |
| Morning | Your accounts had no push subscription, so the 07:30 nudge had nowhere to go. Now at the morning time the coach checks the day, prepares the session and writes a short report into the chat (and pushes it). Today warns when notifications are off; Settings can write the report now. Any coach message can be read aloud by the device |
| Look | No lightning icons on buttons, no em-dash copy, no gradients |

## Result (2026-11-15)
- **Tests:** 38 pass (new: duplicate blocking, watch cues, detail sheets, sheet isolation).
- **C6 with cues:**
  - 100% valid on the first try (v4: 80%);
  - judge 4.15 (v4: 3.94).
- **Verified** with a seeded demo user, at 1280 px light and 375 px dark:
  - the workout card, Health charts, Training goals and gear, the day page;
  - item and meal sheets;
  - the duplicate finder (a real call merged two watch entries and kept the strap);
  - the morning report (a real call).
- **Not verified:**
  - a push reaching a real phone (no device is subscribed yet);
  - which extra wellness fields your Garmin actually sends to intervals.icu (checked after
    deploy).
