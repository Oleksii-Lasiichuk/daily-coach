# 05 — Evaluation

CRISP-DM phase 5.
- **Run:** `uv run python -m evals.run_all` (one component: `uv run python -m evals.run_c5`).
- **Raw results:** `evals/results/*.json`, which include every failure. The first run, before the
  fixes described below, is kept in `evals/results/v1/`.
- **Date:** 2026-11-14 (v3), C1/C6/C8 and prompt injection re-run on 2026-11-15 (v4).
- **Models:** Gemini 3.1 Flash-Lite and Gemini 3.8 Flash via OpenRouter.

## How the evaluation is set up

- **Every component is evaluated alone.** Its own inputs go in and its own output is scored, so
  a weak score points to one prompt or one model.
- **Gold data:**
  - Hand-written synthetic cases in Ukrainian, English and mixed. There is no personal data in
    the repo.
  - For nutrition, a public benchmark: 50 meals from NutriBench v2 (CC BY-NC-SA 4.0), plus 10
    Ukrainian meals whose reference values come from standard food tables.
- **Who wrote the cases:** the cases and labels were written while building the system with an
  AI coding assistant (Claude), a different model family from the Gemini models being tested.
  The athlete reviews the labels; label changes are tracked in git.
- **LLM judge:** used only where there is no single right answer (C6 workouts, C8 replies, C0
  slot matching).
  - The judge is Claude Haiku 5.5, again not Gemini, so a model doesn't grade its own family.
  - The rubric is in the eval script.
- **Baselines:** C3 and C5 are compared with simple non-LLM baselines, so the number means
  something.
- **Tracing:** each eval case is traced in Langfuse (environment `eval`, tag `eval`), so any
  failure can be opened and inspected.

## Results

| Component | Data | Metric | Result | Baseline / target |
|---|---|---|---|---|
| C7 Safety gate | 40 msgs, 20 red flags | recall · false-alarm rate | **1.00** · **0.00** | target recall 1.0 |
| C1 Tool routing (v3 agent) | 60 msgs, same labels | macro-F1 over log/plan/profile tools · exact · no write on questions | **0.84** · 0.80 · **1.00** | v2 fixed router: 0.93 · 0.90 |
| C2 Log extractor | 40 msgs, 51 gold events | (kind, day) F1 · day accuracy · field accuracy | **0.91** · 0.94 · 1.00 (19 checks) | target F1 ≥ 0.80 |
| C3 Nutrition (NutriBench) | 50 meals | kcal MAE · within ±20% | **69 kcal** · 72% | predict-the-mean: 191 kcal |
| C4 Sources: facts | 1 synthetic export (36 k chars), 24 planted facts | recall · precision of proposed facts | **1.00** · **1.00** (27 proposed) | – |
| C4 Sources: search | 24 questions (UA/EN) | recall@5 · recall@1 · MRR | **0.92** · 0.46 · 0.60 | v1 (2,800-char chunks): 0.83 · 0.29 · 0.48 |
| C3 Nutrition (Ukrainian) | 10 meals | kcal MAE · within ±20% | **35 kcal** · 80% | predict-the-mean: 112 kcal |
| C5 Day type | 30 day scenarios | accuracy · Cohen's κ | **0.93** · **0.91** | device-only rule: 0.60 · κ 0.49 |
| C6 Planner + validator | 20 scenarios | valid first try · after 1 retry · judge 1–5 | 0.85 · **1.00** · 4.11 | v1: 0.80 · 1.00 · 3.73 |
| C0 Interviewer | 5 simulated athletes | slot coverage · slot accuracy · redundant questions | **1.00** · 0.89 · **0** | target ≥ 0.9, 0 redundant |
| C8 Coach answers (v3 agent) | 15 questions | correct · grounded · says "missing" | **1.00** · 1.00 · 1.00 | v2 reply writer: 1.00 · 1.00 · 1.00 |
| Prompt injection (v4 agent) | 10 file excerpts with hidden instructions (UA/EN) | attack success (write tool or payload in answer) · uses the real fact | **0.00** · 1.00 | without the untrusted wrapper: 0.00 · 1.00 |

These are the final numbers after the redesign; prompts changed for the setup form, the day
summary, file excerpts and the 14-day history. All components were re-run on 2026-11-14.

**v4 re-run (2026-11-15).** The coach prompt changed (photo meals are confirmed first; no
Garmin Coach assumption; the injection rule), and so did the planner prompt (weather), so C1,
C8 and C6 were run again:

| | v3 | v4 |
|---|---|---|
| C1 macro-F1 · exact · no write on questions | 0.84 · 0.80 · 1.00 | 0.83 · 0.78 · **1.00** |
| C8 correct · grounded · says "missing" | 1.00 · 1.00 · 1.00 | 1.00 · 1.00 · 1.00 |
| C6 valid first try · after retry · judge | 0.85 · 1.00 · 4.11 | 0.80 · 1.00 · 3.94 |
| C6 with step cues (v5: every step names the exercise) | | **1.00** · 1.00 · **4.15** |

These changes are within the run-to-run spread we saw before (C6 judge 3.98–4.11, first-try
validity 0.85–0.90): one case is 1.7 points on C1 and 5 points on C6. The eval sets have no
weather or photo cases, so they measure that nothing broke, not the new rules.

C3 detail (MAE, NutriBench / Ukrainian):
- carbs 11.2 / 4.8 g (baseline 29.0 / 15.7)
- protein 2.7 / 1.8 g (baseline 8.3 / 9.8)
- fat 4.5 / 2.8 g (baseline 9.6 / 9.0)

C6 judge criteria (1–5): safety fit 4.7, respects the athlete's own plan 4.15,
specificity 3.7, rationale 3.9.

## What the errors show, and how to improve

**C1 in v3 (tool routing, 0.84).**
- **What the mismatches are:** the gold labels describe a router; the agent works differently.
  - Most mismatches are the agent doing *more* than the label: `assess_day` after "slept 4 h,
    6 beers", or `save_item` for "sore throat". Its instructions ask for that.
  - The real misses are three "can I run / race tomorrow?" messages where it logged but didn't
    plan. A prompt rule was added for this case.
- **What matters most:** the coach never called a write tool for a pure question or small talk
  (1.00).
- **Improve:** re-label the set for the agent's behaviour ("a bad day → assess"), and add
  multi-turn cases ("так", "Skip it" need the previous question).

**C8 in v3.**
- **First run:** 4 of 15 answers were *empty*. The coach prompt asks for tools, and the eval
  provides none.
- **Fix in the app:** if an answer is empty, the coach is asked once more without tools.
- **Fix in the eval:** it now says tools aren't available.
- **After:** 15 of 15 correct and grounded.

**C7 Safety (perfect score).**
- **What it shows:** the set is small and the red flags are clear-cut. The score shows the
  prompt covers the categories; it doesn't prove recall on rare, vague phrasing ("щось
  дивно тисне").
- **Improve:** collect real borderline messages from use and add them to the set.
- **Design choice:** for safety we accept more false alarms, and the prompt says "when in
  doubt, flag".

**C1 Router (0.93), 7 of 60 messages wrong.**
- **Error pattern:** every error is on a boundary that is ambiguous for people too:
  - "can I run tomorrow?" is both question and plan;
  - gear and asthma statements are labelled `log` + `profile`;
  - very short answers ("так", "Skip it") are routed without the interviewer's question as
    context.
- **Effect:** extra intents are cheap (one more component runs), but missing `plan` loses the
  workout card. So `plan` recall matters most.
- **Improve:** pass the last assistant question to the router (the app already does this; the
  eval doesn't). Or merge question/plan when the message asks about training.

**C2 Extractor (F1 0.91).** The errors fall into two groups.
1. **"Ввечері" said in the morning:**
   - "Випив 0.33 пива ввечері" was dated today in the gold label and yesterday by the model.
   - "Ввечері прийняв магній" went the other way.
   - Both readings are defensible at 09:30. The ambiguity is real: the app should store the
     time and show it, so the user can correct it in one tap.
2. **Over-extraction:** "HRV looks good" became an extra `note`; "after yesterday's shawarma"
   became an extra yesterday `meal`. These cost precision (0.89) more than recall (0.94).

- **Improve:** a short rule in the prompt ("don't log things mentioned only as a cause"), and
  dedupe `note` events.

**C3 Nutrition.**
- **Compared with the baseline:** it is about 3× better than the baseline on both sets.
- **Biggest errors:**
  - unusual foods from low-resource cuisines (millet flour with husks in a Zambian meal:
    211 vs 679 kcal);
  - portion words like "footlong sub" and "a quiche", with the model over-estimating by 40–75%.
- **Label quality:** one NutriBench label looks wrong ("507 g sweetened carbonated water" =
  0 kcal).
- **Ukrainian meals:** the model does better here (MAE 42 kcal). These meals state their gram
  amounts, and the dishes are common.
- **Improve:** look up foods in a database (USDA FoodData Central / Open Food Facts) for the
  per-100 g values, and keep the LLM for splitting the meal and estimating portions. This
  is the ablation planned in the business-understanding doc.

**C4 Sources.**
- **Fact extraction:** all 24 planted facts were proposed, with no false facts (27 proposals,
  where some facts are split in two). The test export is clean, though: one person and no
  contradicting old facts. Real exports will have outdated facts ("took antibiotics in 2025"),
  which is why the user confirms each fact and can mark it resolved.
- **Search:** the right passage is in the top 5 for 92% of questions but first in only 46%.
  - The passages are mostly assistant advice, and the person's sentence is a small part of
    them.
  - Halving the chunk size (2,800 → 1,400 characters) raised recall@5 from 0.83 to 0.92 and
    MRR from 0.48 to 0.60.
  - **Caveat:** this setting was chosen on the same set it is reported on, so the second number
    is optimistic.
- **Improve:**
  - embed only the person's own turns (drop assistant text from the index);
  - add keyword search for names and numbers (hybrid search);
  - build a separate held-out export.

**C5 Day type (κ 0.91 vs 0.49 for the rule).**
- **Why it beats the rule:** the gain comes from what the athlete says. The device-only rule
  can't see alcohol, illness, pain or a doctor's instruction, which is exactly why the
  system reads free text.
- **The 2 errors:**
  - a mild runny nose with HRV −9% was called *recover* (label *easy*): over-cautious, which
    is acceptable;
  - a perfectly average day was called *push* (label *normal*).
- **Every prediction is within one level** of the label.
- **Improve:** show the user the reasons and let them overrule; log those overrides as new
  labels.

**C6 Planner.**
- **First run (v1):**
  - 80% valid on the first try;
  - judge 3.73;
  - specificity only 3.05: 4 of 20 proposals were just a warmup block (e.g. "50 min threshold
    run" with 15 min of steps).
- **Fixes:**
  1. a validator rule that requires a main set;
  2. a prompt rule that the steps must add up to the stated session;
  3. concrete HR numbers in the rationale.
- **After:** 85–90% valid on the first try across runs, 100% after one retry, judge 3.98 →
  4.11 in the final run, specificity 3.65–3.7.
- **What still costs points:**
  - strength sessions are a single block without exercises (the intervals.icu format has no
    place for them);
  - targets are zones rather than exact paces.
- **Safety:** the hard rules are checked by code, not trusted to the LLM, so safety fit is
  the highest criterion (4.55).

**C0 Interviewer.**
- **Results:** all 10 slots filled for all 5 simulated athletes in 4.4–4.8 turns on average,
  with 0 questions about already known fields.
- **Slot accuracy 0.89–0.96 across runs:** the misses are paraphrases the judge counted as different (e.g. a
  shortened gear list).
- **Limitation:** the simulated user is cooperative. Real people skip and digress, and the
  "skipped" value handles that.

**C8 Reply.**
- **First run:**
  - 0.87 correct. The model read intervals.icu's HR zone list (zone *upper limits*) as lower
    limits and answered zone 2 = 143–164 bpm instead of 124–143.
  - It also added unrelated logs to answers.
- **Fixes:**
  - the app now stores zones as explicit ranges (`Z2: 124-143`), a data representation fix
    rather than a prompt fix;
  - the prompt says "answer first, only confirm logs made this turn".
- **After:** 0.93 correct after the fix; 1.00 correct and 1.00 grounded in the final run.

**Prompt injection (new in v4).**
- **Setup:** `evals/run_injection.py`. The athlete asks a question, and `search_memory`
  returns an excerpt from "their" file with a hidden instruction. The 10 attacks are: change
  the weight, set a reminder that leaks a key, log fake beers, end all items, say "PWNED",
  claim a 3-hour run is on the watch, store a fake plan, delete reminders, add a phishing link,
  and "developer mode". We check whether the next step calls a write tool, or the answer
  contains the payload.
- **Result:** 0 of 10 attacks succeeded, and 10 of 10 answers still used the real fact from the
  excerpt.
- **Ablation:** the same result without the `<untrusted_file_excerpts>` wrapper, so the
  prompt rule (and the model) already resist these simple attacks. The set is too easy to show
  what the wrapper adds.
- **Guarantees that don't depend on the model:**
  - `update_profile` accepts only 10 known keys, so a file can't rewrite the coach's
    instructions;
  - facts from files are only *proposed* until the athlete keeps them;
  - nothing reaches the watch without **Send to watch**;
  - every action has **Undo**.
- **Improve:** add indirect attacks through images (text in a screenshot) and multi-turn
  attacks, and test with the cheaper Flash-Lite model.

## Limitations of this evaluation

- **Sets are small:** 15–60 cases each. A 1-case change moves accuracy by 2–7 points, so the
  numbers show the level, not small differences.
- **Gold labels:** written by one annotator for one athlete; agreement between annotators
  was not measured.
- **Some metrics depend on an LLM judge:** C6 and C8. We used a different model family and
  kept the judge's comments in the result files so they can be checked.
- **No end-to-end evaluation with real use yet:** the next step is to label two weeks of
  real chats and measure the whole pipeline.
