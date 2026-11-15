# Demo script (≤ 10 min) — v4

Record https://coach.lasiichuk.com on desktop (with the side panel) and on the phone; keep
Langfuse open in another tab.

| Time | Show | Say |
|---|---|---|
| 0:00–0:40 | Today, light theme | The problem: a watch plan doesn't know I drank, slept badly, got sick or bought new shoes. Daily Coach is an agent: I tell it my day, it does the rest. |
| 0:40–1:40 | First-run window (Settings → Advanced → Run setup again): intervals.icu link, about you + "Do you follow a plan?", goals, files | Required setup in 5 steps. A ChatGPT export is read; facts come with the quote they came from; I keep what's right (C4). Step 5 asks only for what is still missing (C0). |
| 1:40–3:30 | Voice: "Вчора 2 пива, спав 6 годин, зранку вівсянка і 2 чаї. Купив Salomon Speedcross 6. За планом 6 по 800." | Voice transcribed (UA/EN). Action lines with Undo: logged with kcal (C2 + C3), gear saved, session proposed. Side panel: day type → **Why?** with evidence (C5); tiles say "usual 58" = my 7-day average; the session card shows **plan → coach** and **fuel** (C6 + validator). |
| 3:30–4:20 | Photo of a plate → the coach lists "rice ~150 g, chicken ~120 g — right?" → "так" | Photo meals are confirmed before logging. Then Nutrition: fix a meal ×½ or set kcal. |
| 4:20–5:00 | Quick log: coffee, water; habits checkbox; focus menu (Auto/Training/Nutrition/Health, Think harder) | One-tap logs with Undo. The focus menu says what each mode does. |
| 5:00–6:00 | "Я на антибіотиках до неділі, о 8 і 20" → Health (item) → Settings → Reminders | The agent saves the medication with an end date and creates push reminders; all reminders live in one place. |
| 6:00–7:00 | Health: explained charts, weight goal line, pain trend, **patterns** ("after alcohol HRV −15%"); Training: race countdown, shoe km; Journal: week vs last week, add to a past day | Patterns are computed in code from my own days, not generated. |
| 7:00–7:30 | Language switch → Українська | The whole interface in Ukrainian; chat and data stay as written. |
| 7:30–8:15 | Langfuse trace `handle-chat-turn` | One trace per message: safety check, each coach step, every tool with input and output, tokens and cost (~$0.01). |
| 8:15–9:30 | `docs/report/05-evaluation.md` | Every component has its own metric. C5 beats the watch-only rule (κ 0.91 vs 0.49). Prompt injection: 0 of 10 attacks succeed, and the defences in code don't depend on the model. |
| 9:30–10:00 | AGENTS.md, skills, plans 01–06 | How the coding agent was steered: plan → implement → verify, security rules, Langfuse/Neon skills. |
