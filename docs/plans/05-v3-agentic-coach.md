# Plan 05 — v3: agentic coach, nutrition, health, training, reminders

CRISP-DM phase: 4. Modeling (agent + tools), 6. Deployment (UI), 5. Evaluation (updated).
Status: approved by Oleksii in chat (answers to the 10 questions, 2026-11-14); building now.

## Decisions (from the interview)

| Topic | Decision |
|---|---|
| Look | ChatGPT-like UX. Two themes with a toggle: **light**, calm and warm, and **dark**, sporty and data-rich. Desktop has 3 panes (nav · chat · today panel); the side panes are resizable and the widths are remembered. Little empty space |
| Phone | Bottom tabs. On Today, the today panel becomes a compact strip above the chat (Day · Session · Fuel · Insight) |
| AI autonomy | Everything you say is acted on directly through tools: meals, logs, gear, goals, races, conditions, medication, reminders, profile. Each action shows as a one-line note with **Undo**. Only changes to training on the watch ask first (Apply) |
| Models | Default **Gemini 3.8 Flash** (coach agent). **Think harder** = Claude Sonnet 5.5. Cheap Gemini 3.1 Flash-Lite for extraction tools. Per-user choice in Profile. No Opus |
| Week | The coach sees the week: Garmin Coach's plan (told in chat or sent as a **screenshot**; Garmin Coach doesn't reach intervals.icu), what's done, and how you are. It can plan easier days so you're fresh for Garmin's key session |
| Nutrition | Log by text, voice or **photo**. Per meal: kcal, protein, carbs, sugar, fibre, fat, saturated fat, salt, caffeine, alcohol, and key micronutrients (iron, calcium, potassium, magnesium, vitamins C and D). Targets depend on day type and weight. Suggestions come from **foods you actually eat**, with variety and "too much of" warnings (e.g. caffeine from tea) |
| Health | A year of wellness and activities synced from intervals.icu. Charts for HRV, resting HR, sleep, weight, VO2max, fitness and fatigue. Conditions, medication and lab results (from uploaded files) |
| Nudges | Web push (installed app): morning plan, breakfast, lunch and dinner reminders, evening log, and medication reminders the coach creates. Times are adjustable in Profile |
| Imports | txt / md / json, including ChatGPT `conversations.json`. Strava and Apple Health are skipped: intervals.icu already has that data from Garmin, and Apple Health exports are huge XML files |
| Users | You and Ivan. Each user can add their own OpenRouter key (it's used when present); otherwise the owner's key with a monthly cap per user |
| Limits | Profile → Usage shows OpenRouter credit live, plus the free-tier limits of Neon, Langfuse, Cloud Run, Firebase and Cloud Scheduler |

## Architecture change: the coach is an agent

```
message (+photo/voice) ─┬─ C7 safety (parallel)
                        └─ Coach agent (Gemini 3.8 Flash, tools, ≤ 6 steps)
                             tools: log_day → C2 + C3 · log_photo (vision) → C3
                                    assess_day → C5 · plan_sessions → C6 + validator (Apply)
                                    save_item / end_item (goals, races, gear, conditions,
                                      medication, preferences; long-term or until a date)
                                    set_reminder · update_profile
                                    nutrition_summary · health_summary · search_memory → C4
                             → reply + list of actions taken (Undo)
```

- **C1 becomes tool routing.** The 60-message router set is re-scored as "did the agent call
  the right tools" (log → log_day, plan → plan_sessions/assess_day, profile →
  save_item/update_profile, question/chitchat → no write tool).
- **Facts become "knowledge items",** with `term` (long / current), `until`, and `details` (e.g.
  race target time or pace, gear km).

## Build order (tonight)

1. Shell: themes, 3 resizable panes, phone tabs, chat bubbles, tool lines, mandatory first-run window.
2. Agent + tools + knowledge items + Undo.
3. Nutrition: extended estimator, the page (today/7/30 days, distribution, micronutrients, top
   foods, suggestions), photo logging.
4. Health: year sync, charts, conditions and labs.
5. Training: week view, Garmin screenshot, plan the week.
6. Profile: models, theme, own key, notification times, usage and limits.
7. Reminders + web push + Cloud Scheduler tick.
8. ChatGPT `conversations.json` import.
9. Evals (C1 as tool routing, C3 extended), tests, deploy, docs.

If time runs short, cut in this order: own OpenRouter key → conversations.json → week planning
(keep the screenshot) → push (keep the reminders list on Today).

## Result (2026-11-14, ~00:00)

**Built:**
- **The coach agent:** 11 tools, Undo on every action, the safety gate in parallel, Think harder
  (Sonnet), per-user model choice and own key.
- **Screens:** light and dark themes; 3 resizable panes; phone tabs with the today strip.
- **Pages:** Today, Training (week, gear, races), Nutrition (16 nutrients against targets, top
  foods, flags, suggestions), Health (a year from intervals.icu, 8 charts, conditions,
  reminders, zones), Knowledge (instructions, items, sources + inbox), Journal, Profile (models,
  key, reminder times, usage and limits).
- **Inputs:** photo logging and Garmin screenshots (vision); voice transcribed by Gemini.
- **First run:** a required 5-step window.
- **Reminders:** web push with VAPID keys, a Cloud Scheduler job every 15 min, and a nightly
  insight.
- **Imports:** ChatGPT `conversations.json`.

**Verified:**
- 25 tests pass.
- Desktop at 1440 px, light and dark; phone at 375 px.
- A real agent turn: it logged, saved gear, refused intervals and proposed rest.
- A drawn Garmin week screenshot: 7 days saved.
- Voice: webm, mp4 and wav transcribed, Ukrainian kept.
- Year sync: Health charts shown.
- First-run steps 1–3 clicked through.
- Evals: C1 0.84 (tool routing), C3 69/35 kcal, C8 1.00.

**Not verified:**
- push delivery to a real phone;
- photo logging with a real meal photo;
- your real sign-in on the phone after the redirect fix;
- a nightly insight on real data.
