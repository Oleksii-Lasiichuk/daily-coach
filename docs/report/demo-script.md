# Demo video script (≤ 10 min) — v6

Recorded **locally** (`uv run uvicorn …` on screen) on the synthetic **Demo Athlete**, so no
real health data is shown. Target length 9:00–9:30.

## Before recording

- Terminal 1: `uv run python -m app.demo seed` (fresh demo athlete), then
  `uv run uvicorn app.main:app --port 8000`. Keep it visible for a few seconds at 2:20.
- Browser tabs, in order:
  1. `docs/report/README.md` on GitHub (diagram renders there);
  2. http://localhost:8000/login (1280 px wide, light theme, English);
  3. Langfuse project, Traces, environment `dev`;
  4. `docs/report/05-evaluation.md` on GitHub, scrolled to "Current results";
  5. `AGENTS.md` and `.claude/skills/` on GitHub;
  6. `docs/report/07-agentic-coding.md`, the "What went wrong" table.
- A meal photo on the desktop (any plate of food).
- Mute notifications. Close other tabs. Zoom the browser to 110% so text is readable.

## Script

| Time | Show | Say |
|---|---|---|
| 0:00–0:45 | Report README, section 1 | "I train with a Garmin watch. Its plan knows my sleep and heart-rate variability, but not that I drank last night, that my knee hurts or what I ate. Daily Coach is a chat assistant: I tell it about my day in Ukrainian, English or both, it keeps a structured log, decides what kind of day it is and adapts my workout, which goes to my watch only when I press Send." |
| 0:45–1:15 | Report README, section 2 (requirements) | "The requirements: understand mixed-language text with relative dates; log food with nutrients; explain every decision; never touch the watch without my confirmation; and stop training advice on medical red flags." |
| 1:15–2:20 | Report README, diagram + component table | "Every message goes to two things in parallel: a safety gate, C7, and a coach agent with eleven tools. The tools are the NLP components. C2 extracts events and resolves dates. C3 estimates nutrition, and the totals are computed in code. C5 classifies the day type. C6 writes the workout, and a code validator checks hard rules: no hard intervals on a recovery day, the steps add up. C4 reads uploaded notes, proposes facts with the quote they came from, and searches them. Retrieval is one tool of eleven, so this is not a RAG system. External calls: OpenRouter for the models, intervals.icu for watch data and workouts, Open-Meteo for weather, Langfuse for tracing." |
| 2:20–2:45 | Terminal, then the login page → **Open the demo athlete** | "This is running locally from the README. I sign in as a synthetic demo athlete with a year of generated watch data, so there is no personal data on screen." |
| 2:45–4:30 | Today. Type: `Вчора 2 пива, спав 5 годин, зранку важка голова. На сьогодні 6 по 800. Що робити?` Wait for the answer (point at "Working · N s"). Then: action lines → day card **Why?** → session card → **Send to watch** | "Case one: mixed language and relative dates. … The coach answered in Ukrainian. Under the answer: three logs. Beer is on Saturday, yesterday; sleep is on Sunday, because sleep belongs to the morning you wake up. The day card says Recovery day, and Why shows each reason with its number: sleep 5.2 hours against my usual 7, HRV 47 against 67. The tiles show the drop in orange. My plan said 6 by 800 metres; the planner replaced it with a 30-minute easy jog, every step with an exercise and a heart-rate limit. Nothing is on the watch yet. Now I press Send to watch, and it goes to the intervals.icu calendar, then to Garmin." |
| 4:30–5:15 | Langfuse: open the newest `handle-chat-turn` trace; expand the safety call, `log_entries`, `assess-day-type`, `plan-workout` | "Every message is one trace. The safety gate ran in parallel and found no red flag. Then the agent steps: each tool call with its input and output, the model, tokens and cost. This turn took about half a minute and cost one to two cents." |
| 5:15–6:00 | Today: attach the meal photo, send. The coach lists items with grams and asks to confirm; reply `так`. Open Nutrition, press ×½ on that meal | "Case two: a photo. The coach lists what it sees with grams and asks me before logging anything. Estimates have errors, so every meal can be fixed: half, double, my own calories or new text. The page shows the measured error on a public benchmark." |
| 6:00–6:40 | Today: `Біль у грудях і запаморочення під час бігу вчора, що робити сьогодні?` | "Case three: safety. Chest pain and dizziness is a red flag. The coach gives no workout and tells me to see a doctor. Nothing is planned." |
| 6:40–7:00 | Today: `З'їв 5 кг суші на сніданок` | "And impossible amounts are rejected in code before anything is saved, so this doesn't depend on the model noticing." |
| 7:00–8:30 | 05-evaluation.md, "Current results" table | "Every component has its own eval script and metric, chosen for what matters. Safety: recall, because missing a red flag is the costly error: 20 of 20, but with 20 cases the lower bound is 0.84, so I don't claim more. Day type: Cohen's kappa 0.91, against 0.49 for a rule that only reads the watch, and zero for always guessing the most common class. The gain comes from what I say in text. Nutrition: 69 kcal error per meal on NutriBench, against 191 for predicting the mean. Prompt injection: 0 of 10 attacks. And a new end-to-end eval: 12 real turns, checked in the database. The first run found a real bug: the coach couldn't see my race date. After the fix all 12 pass, and nothing reached the watch without a tap. The low scores: tool routing 0.83, because my labels were written for an older router; search 0.46 at rank one, because exports are mostly the assistant's text; I explain each and how I would fix it. Not evaluated: voice and vision, and I say why." |
| 8:30–9:20 | AGENTS.md → `.claude/skills/` → 07-agentic-coding.md table | "I built this with Claude Code, controlled by an AGENTS.md: the project, the grading criteria, CRISP-DM, security rules, and what done means: the code runs, the eval result is recorded, and what was not verified is said out loud. Skills: plan, implement, explain, eval, ui-check, and the official Langfuse skill. Every real failure became a rule or a test: reasoning tokens ate the output limit, the model misread heart-rate zones, the coach saved my shoes twice. The assistant also let the documents drift from the code, which an independent review caught." |
| 9:20–9:40 | Report README, section 6 "Limits" | "Limits: small synthetic eval sets with one annotator, and intervals.icu is needed for watch data. Next: evaluate on two weeks of real use. Thank you." |

## If something goes wrong while recording

- The answer takes long: keep talking about the diagram; it usually takes 15–30 s.
- The coach answers differently: read what it did; the point is the dates, the reasons and that
  nothing is sent without the button.
- To start over: `uv run python -m app.demo seed`, reload the page.
