# 04 — Modeling

CRISP-DM phase 4. The system is a pipeline of small, separately evaluated LLM components plus
code. It is not one big prompt and not RAG.

## Components

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
- **Human in the loop.** Nothing is written to intervals.icu until the user presses **Apply**;
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
  only when the chat actually does the setup work. Our setup needs specific inputs, so it is 4
  short steps. C0 runs in step 4 and asks ≤ 5 questions about what is still missing after
  intervals.icu, the form and the files.
- **Voice input.** The browser's speech recognition (Web Speech API, `uk-UA` / `en-US`) turns
  speech into text, which you check before sending. A server-side speech-to-text model
  was the alternative; it lost on cost and time for this submission.

## Main alternative considered

One agent with tools (read wellness, write logs, create workout) instead of a fixed pipeline. It
lost because:
- it is harder to evaluate per component;
- it is harder to guarantee "no write without Apply";
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
- the watch is only written after **Apply**;
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
| Patterns | 90 days of logs + wellness → "after alcohol your next-morning HRV is 15% lower (10 nights vs 50)" | Compare next-morning HRV, resting HR and sleep after tagged days (alcohol, a meal after 21:00, > 300 mg caffeine, < 6.5 h sleep) with other days; shown only with ≥ 3 vs ≥ 5 nights and ≥ 5% difference (`app/patterns.py`) |
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
