# Plan 09 — The next version: workflows first

CRISP-DM phase: 1. Business understanding (next iteration). Status: proposal, not started.

## Goal

v1–v6 added features page by page. The next version should be designed around the five
moments in an athlete's day when they actually open the app, and make each one take under a
minute. Everything else (charts, memory, settings) supports those moments.

## The five moments

| Moment | Today (v6) | Best version |
|---|---|---|
| **Morning check-in** (07:00, 30 s) | Morning report in chat; you open Today, read the day card, maybe press Send to watch | One notification: "Recovery day: HRV −29%, 2 beers. Swap 6×800 for a 30 min easy jog?" with **Send to watch** / **Keep my plan** buttons. Answering logs how you feel. No app opening needed |
| **Log as you go** (during the day, 5 s each) | Chat, quick log chips, photos with confirmation | Same, plus a share-sheet target ("Share to Daily Coach" for a photo or a Garmin Coach screenshot) and a home-screen widget with water/coffee/meal buttons |
| **After the workout** (10 s) | Nothing; the run syncs silently | When a new activity syncs, ask one question: "How did it feel, 1–10? Any pain?" The answer feeds C5 tomorrow and the pain trend |
| **Evening wind-down** (21:30, 20 s) | Evening nudge | "Today: 2,100 kcal, protein 40 g short, 9,800 steps. Tomorrow: long run 18 km. Eat carbs tonight, in bed by 23:00?" with a one-tap habit check |
| **Weekly review** (Sunday, 2 min) | Sunday push + Journal week tiles | A one-screen review: load vs last week, what helped and hurt (patterns), next week's plan from C6 for several days, one **Send all to watch** |

## Product principles

1. **The watch is the main screen.** The app's job is to put the right workout on it; the
   app is where you explain why and correct it.
2. **Ask at the moment, not in a form.** Each question comes when the answer is fresh
   (RPE after the run, sleep in the morning).
3. **Code for numbers, LLM for language.** Keep it: totals, patterns, limits and validation in
   code; extraction, explanation and planning by the model.
4. **Every claim shows its evidence**, and small samples say "weak".
5. **Nothing irreversible without a tap**, and every action has Undo.

## Features, in order of value

1. Actionable morning notification with Send / Keep buttons (push actions already exist).
2. Post-activity RPE + pain question on sync (the hourly sync already sees new activities).
3. Manual mode without intervals.icu: log runs in chat; Strava or Apple Health import later.
   This removes the biggest drop-off in setup.
4. Week planning: C6 for 7 days in one call, one Send for the week, conflicts with the user's
   own plan shown side by side.
5. Food-database grounding for C3 (USDA / Open Food Facts), the ablation the proposal promised.
6. Coach mode: one human coach, several athletes; the AI proposes, the coach approves. The
   research in plan 06 found this is the gap in the market.
7. Data export and account deletion (GDPR basics).

## Evaluation for the next version

- Label two weeks of real use (both users) and re-run C1, C2, C5 on it.
- Measure the moments: time from notification to Send, share of mornings with a decision,
  share of activities with an RPE answer.
- A vision eval: 20 plan screenshots and 20 meal photos with hand-checked labels.
