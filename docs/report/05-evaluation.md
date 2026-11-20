# 05 — Evaluation

CRISP-DM phase 5.
- **Run:** `uv run python -m evals.run_all` (one component: `uv run python -m evals.run_c5`).
- **Raw results:** `evals/results/*.json`, which include every failure. The first run, before the
  fixes described below, is kept in `evals/results/v1/`.
- **Date:** 2026-11-14 (v3); C1, C6, C8 and prompt injection re-run on 2026-11-15 (v4, v5);
  C2 and the end-to-end agent run on 2026-11-15 (v6). The table below is the current one.
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
  There was one annotator and no second labelling pass; label changes are tracked in git.
  The evals still found real errors (empty C8 answers, HR zones read as lower limits, sleep put
  on the wrong night), so the sets are not just confirming the prompts.
- **LLM judge:** used only where there is no single right answer (C6 workouts, C8 replies, C0
  slot matching).
  - The judge is Claude Haiku 5.5, again not Gemini, so a model doesn't grade its own family.
  - The rubric is in the eval script.
- **Baselines:** C3 and C5 are compared with simple non-LLM baselines, so the number means
  something.
- **Tracing:** each eval case is traced in Langfuse (environment `eval`, tag `eval`), so any
  failure can be opened and inspected.

## v7 additions (2026-11-20, plan 10)

v7 makes the app usable for family members (see `docs/plans/10-v7-life-os.md`). New and changed
measurements:

| What | Cases | Metric | Result | Notes |
|---|---|---|---|---|
| **C9 Day review (new)** | 15 synthetic days (`evals/make_c9_days.py`), 8 EN / 7 UA | numbers grounded (code) · right language (code) · names the day's main point · no false claim · usefulness 1–5 (judge: Claude Haiku) | **1.00** · 1.00 · **0.93** · **1.00** · 3.6 | main point 14/15 (95% CI 0.70–0.99); no false claim 15/15 (0.80–1.00) |
| End-to-end agent | 14 turns (2 new: a meal photo, then a correction) | case pass rate · nothing sent without a tap | **1.00** (14/14) · yes | the photo is logged at once ("Записав: гречка ~150 г…"); "no, 250 g" replaces the entry instead of adding a second one |
| Page speed (A2) | 7 pages × 2–3 loads, demo athlete | server time from `Server-Timing` | Today 2.4–2.6 s → **0.18–0.29 s** (+ side panel 0.5–0.7 s after the page); Training 2.6–2.8 → 0.64 s; Health 2.4 → 0.82 s; Nutrition 1.9–2.1 → 0.5–0.7 s | measured from a laptop to Neon in Frankfurt (~35 ms per round trip), so prod (Cloud Run in Belgium, ~8 ms) is faster still |
| Chat survives leaving the page (A1) | test + browser | reply saved and shown after Today → Nutrition → Today | **yes** | `tests/test_v7.py` also checks that another page loads while a turn runs |
| Translations (A4) | every `_()`, `t()`, error message and label list | keys without Ukrainian | **0** | `scripts/i18n_check.py`, run as a test; a rendered-page scan in UA finds only user data and site names |

**C9: what changed between runs.** The first prompt let the model compare numbers itself.
Run 1: main point noticed 0.60, no false claim 0.60, usefulness 3.1. Its false claims were
comparisons ("you met your protein target" at 120 of 135 g), and it missed alcohol, caffeine
and meal timing. The fix follows the project rule *code for numbers, LLM for language*:
`day_review.analyse` computes each target's status (on target = within ±10%), the limits, and
a ranked list of issues (alcohol, caffeine, macro gaps weighted by day type, no breakfast on a
hard day, late eating, low water). The model only puts the worst issue into words. Run 2: 0.93
· 0.93 · 3.5. Then a wording rule ("close to the target", never "perfectly") and energy-aware
tips gave run 3: 0.93 · 1.00 · 3.6.

Two eval changes between runs, made deliberately: the judge now sees the same `analysis` as the
model (before, it called the 20 g alcohol limit "invented"). Five cases also had 2–4 expected
points cut to the main one, because a three-sentence review cannot hold four. Usefulness stays
under the 4.0 target. The judge's comments say the tips are correct but generic ("add more
buckwheat"). The next step is a small food table so the tip can say how much of which food
closes the gap.



One row per component, final run. `k/n` and the 95% Wilson interval come from
`uv run python -m evals.stats` (`evals/results/intervals.json`). With 10 to 60 cases the
intervals are wide, so read the numbers as levels, not as small differences.

| Component | Cases | Metric | Result | 95% CI | Baseline | Why this metric |
|---|---|---|---|---|---|---|
| C7 Safety gate | 40 (20 red flags) | recall · false-alarm rate | **1.00** · 0.00 | 0.84–1.00 · 0.00–0.16 | target recall 1.0 | Missing a red flag is the costly error, so recall first; false alarms only cost a warning |
| C1 Tool routing (agent) | 60 | macro-F1 · exact match · no write on a pure question | 0.87 · 0.80 · **1.00** (earlier runs 0.83–0.84) | exact 0.68–0.88 | v2 fixed router 0.93 · 0.90 | Tools are a multi-label choice, so F1; a write on a question is the harmful error, so it is reported alone |
| C2 Log extractor | 43 (59 gold events) | (kind, day) F1 · day accuracy · field accuracy | **0.92** · 0.95 · 1.00 (23 checks) | – | target F1 ≥ 0.80 | A log is useful only with the right kind **and** the right day; dates are the hard part in UA/EN |
| C3 Nutrition | 50 NutriBench + 10 Ukrainian | kcal MAE · share within ±20% | **72 kcal** · 73% (NB); **35 kcal** · 90% (UA); earlier runs 69 kcal | – | predict-the-mean 191 / 112 kcal | MAE is in the unit the user feels (kcal); ±20% is the usual tolerance of food labels |
| C4 Facts from files | 1 export, 24 planted facts | recall · precision | **1.00** · 1.00 (27 proposed) | – | – | Facts are confirmed by the user, so recall matters most; precision shows the review load |
| C4 Search | 24 questions | recall@5 · recall@1 · MRR | **0.92** · 0.46 · 0.60 | r@5 0.74–0.98 | v1 chunks 0.83 · 0.29 · 0.48 | The coach reads the top 5 excerpts, so recall@5 is what reaches the model |
| C5 Day type | 30 | accuracy · Cohen's κ · within one level | **0.93** · **0.91** · 1.00 | acc 0.79–0.98 | majority class 0.33 · κ 0; device-only rule 0.60 · κ 0.49 | Classes are ordered and imbalanced: κ corrects for chance, "within one level" shows how bad the misses are |
| C6 Planner + validator | 20 | valid first try · after 1 retry · judge 1–5 | **1.00** · 1.00 · 4.15 | first try 0.84–1.00 | v1: 0.80 · 1.00 · 3.73 | The retry hides cost and latency, so first-try validity counts; a judge scores what code can't (fit, specificity) |
| C0 Interviewer | 5 simulated athletes | slot coverage · slot accuracy · redundant questions | **1.00** · 0.89 · **0** | – | target ≥ 0.9, 0 redundant | Setup must fill what is missing without asking what is known |
| C8 Coach answers | 15 | correct · grounded · says "missing" | **1.00** · 1.00 · 1.00 | correct 0.80–1.00 | v2 reply writer: same | Health answers must be right **and** come from the user's data, or say the data is missing |
| Prompt injection | 10 attacks | attack success rate · uses the real fact | **0.00** · 1.00 | 0.00–0.28 | without the wrapper: 0.00 · 1.00 | Any successful attack is a failure, so the rate of success; utility shows the defence didn't break answers |
| **End-to-end agent (new)** | 12 turns, 34 checks | case pass rate · check accuracy · nothing sent to the watch without a tap | **1.00** · 1.00 · **yes** (12/12); first run 0.92 | cases 0.76–1.00 | – | Checks what lands in the database (kinds, dates, items, reminders, proposals) after a real turn, not just the reply |

C3 macro detail (MAE, NutriBench / Ukrainian, run of 15 Nov evening): carbs 11.9 / 3.2 g
(baseline 28.7 / 15.7), protein 2.7 / 1.7 g (8.5 / 9.8), fat 4.2 / 2.6 g (9.4 / 9.0). One
NutriBench meal failed to parse (49 scored). Across three runs the NutriBench kcal MAE was 68.8,
69.1 and 71.5: the spread between runs is about 3 kcal. C6 judge criteria (1–5): safety
fit 4.8, respects the athlete's plan 4.2, specificity 3.6, rationale 4.0.

### What is covered how

| Part of the system | How it is checked |
|---|---|
| LLM components C0–C8, prompt injection, the agent end to end | Eval scripts above (`evals/run_*.py`), every case traced in Langfuse |
| Workout validator, rendering to intervals.icu text and watch cues | Unit tests: `test_recover_day_limits`, `test_injury_and_red_flag_and_sport`, `test_warmup_only_is_rejected`, `test_text_and_minutes`, `test_watch_cue_keeps_words_drops_numbers` |
| Patterns (code, no LLM) | `test_patterns_find_alcohol_effect_only_with_enough_nights`, `test_patterns_stay_quiet_on_random_data` (50 random 90-day logs; the old rule fired on 20 of them) |
| Session fuel, quick log, meal edits, impossible amounts | `test_fuel_rules`, `test_scale_and_quick_data`, `test_quick_log_edit_and_undo`, `test_impossible_amounts_are_not_logged` |
| Calorie targets, day digest, Journal chips | `test_targets_use_sex_and_midpoint_when_unknown`, `test_digest_reads_kcal_from_totals_when_top_level_is_missing`, `test_day_chips_sum_the_day` |
| Duplicates, profile key allow-list, untrusted file wrapper | `test_near_duplicates_are_not_saved_twice`, `test_coach_cannot_set_arbitrary_profile_keys`, `test_untrusted_file_results_are_wrapped` |
| Security (sign-in, isolation, CSRF, budget, demo mode) | `test_auth.py`, `test_isolation.py` (two users, every endpoint), `test_budget.py`, `test_demo.py` |

### Not evaluated, and why

| Part | Why not | Risk, and what we do about it |
|---|---|---|
| Voice transcription | A third-party model; no labelled UA/EN audio set | Wrong words are visible: the text lands in the box and is checked before sending |
| Photo meals and plan screenshots (vision) | No labelled image set; real photos would be personal data | The coach lists what it sees with grams and asks to confirm before logging (prompt rule); screenshot plans are shown on the card before anything is sent |
| C3 with a food database (grounded vs LLM-only) | Planned in the proposal, not built in time | LLM-only is already ~3× better than the baseline; grounding is the first next step |
| Pain trend, weather adaptation, week review, morning report | Thin code over stored data, or a re-use of C5/C6 | Covered by the page tests and by C6 (weather goes into its inputs) |
| Real-use accuracy | No labelled real chats yet | Next: label two weeks of real use and re-run C1, C2, C5 on it |

### Earlier runs


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

**C1 in v2, the fixed router (0.93), 7 of 60 messages wrong. Kept for history.**
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
- **Ukrainian meals:** the model does better here (MAE 35 kcal in the final run, 42 in an earlier one). These meals state their gram
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
  the highest criterion (4.55 in v3, 4.8 in the final run).

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

**End-to-end agent (new in v6).**
- **Setup:** `evals/run_e2e.py` re-seeds the synthetic Demo Athlete (a year of watch data, three
  weeks of logs) and sends 12 messages through the real agent: breakfast, a hangover with
  relative dates, a plan to replace, a pure question, new gear, pain, impossible amounts, a
  reminder, a user asking to skip confirmation, a question about the race, a red flag, and an
  English dinner with wine. After each turn it reads the database.
- **First run:** 11 of 12 cases, 33 of 34 checks. Two findings:
  - "Вчора 2 пива, спав 5 годин" was logged correctly (beer yesterday, sleep today), and the
    coach also proposed a session nobody asked for. In the second run it didn't: this case
    varies between runs.
  - "When is my next race?" passed by luck: the coach said it didn't know the race date. The
    race's date and target were in the item's details, which were **not in the coach's
    context**. A real bug for real users; fixed in `agent.context_block`.
- **After the fix:** 12 of 12 cases, 34 of 34 checks; the coach now answers with the date and
  days left. In both runs nothing reached the (fake) watch calendar without a tap, including
  the message that asked for exactly that.
- **Improve:** more multi-turn cases (answers like "так" to a question), and a check of the
  reply language.

**C2 sleep dating (found in the review, fixed in v6).** "Вчора 2 пива, спав 5 годин" put the
sleep on yesterday. The prompt now says a leading "вчора" doesn't move the sleep, and three
cases were added to the C2 set. All three pass; F1 0.91 → 0.92 on 43 cases.

**Patterns (code, fixed in v6).** The first rule (3 tagged nights, a 5% difference) printed
"11% higher sleep after a late meal" on random data. It now needs 5 tagged and 10 other nights
and a Welch t of at least 2.5. Simulated on 200 random 90-day logs: a false pattern in 6.5% of
them (t ≥ 2: 16.5%; old rule: about 40%). The price is sensitivity: a real 10% HRV drop after
drinking is found in 43% of 90-day logs. For a health claim we prefer fewer false ones.

## Limitations of this evaluation

- **Sets are small:** 15–60 cases each. A 1-case change moves accuracy by 2–7 points, so the
  numbers show the level, not small differences.
- **Gold labels:** written by one annotator for one athlete; agreement between annotators
  was not measured.
- **Some metrics depend on an LLM judge:** C6 and C8. We used a different model family and
  kept the judge's comments in the result files so they can be checked.
- **End to end only on synthetic turns:** `evals/run_e2e.py` runs 12 real turns on the demo
  athlete. The next step is to label two weeks of real chats and measure the whole system.

## B2 additions (2026-11-20, plan 11): C13 + C6 "planner respects the calendar"

Data: `evals/data/c13_calendar.jsonl`, 15 synthetic days made by `evals/make_c13_days.py`: office
days, night and early shifts, back-to-back meetings with a 45-min lunch gap, 20-min gaps only, a
travel day with a 22:00 call and an 07:00 flight, weekends, a conference with no window ≥ 30 min,
standups the day after the DST switch, a late party. Each case reuses the athlete context of C6
case 2 (a normal day). Script: `evals/run_c13.py` (registered in `run_all.py`). Result:
`evals/results/c13_calendar.json`.

| Metric | Target | Result |
|---|---|---|
| Overlaps with busy blocks, after the validator loop | 0 | **0** / 15 |
| Overlaps before the validator (the LLM alone) | (reported) | 0 / 15 |
| Valid on the first try | — | 1.0 |
| Fit rate (inside a free window; rest or shortened on a no-slot day) | ≥ 0.9 | **1.0** |
| Sleep-warning recall (4 cases built to need one) | 1.0 | **1.0**, 0 false alarms on the other 11 |

On both no-slot days the planner chose rest. On the other days it picked the morning window
nearest the 07:00 usual training time, or the only window (11:30 on the midday-gap day, 19:30 on
the busy-until-19:00 day). Before the validator the LLM alone made no overlaps either, so in this
run the validator was a safety net that was never needed. With 15 cases this does not prove it is
never needed.

**Parsing (data check for C13)** is covered by unit tests (`tests/test_calendar.py`,
`tests/test_day_windows.py`, all pass): weekly RRULE with EXDATE, a moved occurrence, DST,
UTC and floating times, X-WR-TIMEZONE, all-day single and multi-day, long events, cancelled and
transparent events, the window end (exclusive), HTML pages, files over 5 MB and bad links
rejected.

**C6 regression check** (same 20 cases, no calendar in them): valid first try 1.0, after retry
1.0 (unchanged). The judge mean was 3.96 against 4.15 in the previous recorded run. A second run
on the same code, rate-limited to 4 cases, scored specificity 4.0 against 3.55 in the first, so
the gap is within the judge's run-to-run noise. The new prompt paragraph only applies when
`day_windows` is present.

Limitations: the 15 days are synthetic and use one athlete. The feeds of real Google/iCloud/Outlook
accounts were not connected (synthetic feeds in each provider's style were). The sleep rule
assumes the person goes to bed at the usual bedtime unless an event ends later.
