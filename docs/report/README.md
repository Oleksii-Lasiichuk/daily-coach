# Daily Coach: a tool-using LLM agent that turns a runner's free-text day into an adapted workout on the watch

**Oleksii Lasiichuk** · UCU, NLP course, Assignment 1 · 15 November 2026
**Live system:** https://coach.lasiichuk.com · **Code:** this repository ·
**Appendix:** [all tools, schemas and system prompts](appendix-prompts-and-tools.md)

## Abstract

Sport watches plan training from sensor data, but they don't know what the athlete *says*: that
they drank last night, that a knee hurts, what they ate. Daily Coach is a deployed chat
assistant that reads free text in Ukrainian, English or both (and voice and photos), keeps a
dated structured log, classifies the day (Recovery / Easy / Normal / Push) from watch data plus
the text, and generates a structured workout that reaches a Garmin watch only after the user
presses **Send to watch**. The system is a tool-using agent whose tools are nine separately
evaluated NLP components, with hard rules (dates, totals, limits, workout validation) kept in
code. Each component has its own eval with a stated metric, a baseline where one exists, and
95% intervals. Highlights: day-type κ = 0.91 against 0.49 for a watch-only rule and 0 for the
majority class; nutrition error 72 kcal per meal on NutriBench against 191 for a mean
predictor; 0 of 10 prompt-injection attacks succeeded; 12 of 12 end-to-end turns wrote the
right rows and nothing reached the watch without a tap. The evals found five real bugs, each
now covered by a rule or a test. The main limits are small, synthetic eval sets with one
annotator.

<p align="center"><img src="img/app-today.png" width="820" alt="Today: the coach's answer in Ukrainian, the action lines with Undo, the session card, and the day card with watch numbers"></p>
<p align="center"><sub><b>Figure 1.</b> One message, end to end (synthetic athlete). Left: the answer, three
log entries with Undo, the proposed session replacing the planned 6×800 m. Right: Recovery day with
the evidence, watch numbers against the athlete's own 7-day average.</sub></p>

---

## 1. Problem and motivation

I'm an amateur runner with a Garmin watch. Building tomorrow's workout by hand takes about five
minutes: decide what the day allows, pick a workout type, write it minute by minute with heart
rate targets, save it, sync it to the watch. The watch's own plan can't help on the days that
matter: it doesn't know I slept five hours *because* of two beers, or that my left knee has
hurt since March. For six months I kept all of this in a ChatGPT project, which knew my history
but couldn't read my watch or write a workout to it.

**Goal:** one place where I tell my day in my own words and get, in about 10 to 30 seconds,
(a) a correct log, (b) an explained verdict for the day, and (c) a workout on my watch that fits
that day, my goals and my history, with nothing sent without my OK.

**Users:** me and my brother daily; anyone can sign in with Google and use their own OpenRouter
key; people without Garmin can use sample watch data.

**Out of scope:** diagnosis, season-long periodisation, social features, coaches managing many
athletes (future work, section 10).

## 2. Requirements

| # | Requirement | How it is met | Checked by |
|---|---|---|---|
| R1 | Understand UA/EN/mixed free text with relative dates ("вчора ввечері") | C2 extractor with temporal rules | C2 eval, F1 0.92 |
| R2 | Correct log with nutrition | C2 + C3; totals and plausibility limits in code | C3 on NutriBench; unit tests |
| R3 | Every decision explained | C5 returns reasons with evidence chips | C5 eval; Figure 1 |
| R4 | Nothing touches the watch without the user | No tool can write to intervals.icu; only the button does | E2E eval, 12/12 |
| R5 | Medical red flags stop training advice | C7 gate on every message; validator blocks hard sessions | C7 recall 1.00 |
| R6 | Personal data stays private | Per-user queries, encryption, injection defences | Isolation tests; injection eval |
| R7 | Cheap enough for daily use | Small models for extraction; caps and own keys | Measured in Langfuse |

## 3. Related work

- **Tool-using LLM agents.** ReAct interleaves reasoning and actions [1]; Toolformer showed
  models can learn when to call tools [2]. Daily Coach uses the ReAct-style loop of
  function-calling models, but limits it to 6 steps and keeps each tool a small, testable
  component.
- **Retrieval-augmented generation.** RAG retrieves passages to condition generation [3]. Here
  retrieval is one tool (C4 search) beside fact extraction with quotes; the system is not RAG
  as a whole.
- **Indirect prompt injection.** Instructions hidden in retrieved data can hijack an LLM
  application [4]. This is the main attack surface of an assistant that reads a user's old
  chats, so it gets its own eval and code-level guarantees (section 4.5).
- **LLM as a judge.** Strong models agree with humans on open-ended answers but show
  self-preference [5]; we use a judge from a different model family than the one judged.
- **Nutrition estimation from text.** NutriBench [6] is a public benchmark of meal descriptions
  with reference nutrients; we use a 50-meal sample.
- **Training readiness.** HRV-guided training uses the drop of morning HRV against a rolling
  baseline [7]; fitness/fatigue (CTL/ATL) come from Banister's impulse-response model [8].
  Energy targets use Mifflin-St Jeor [9]; fuelling rules follow Jeukendrup [10].
- **Statistics.** Wilson intervals for small-sample proportions [11]; Cohen's κ for agreement
  beyond chance [12]. **Process:** CRISP-DM [13].

## 4. System

### 4.1 Architecture

```mermaid
flowchart LR
  U["Message<br/>text · voice · photo"] --> S["C7 Safety gate<br/>(in parallel)"]
  U --> A["Coach agent<br/>Gemini 3.8 Flash<br/>≤ 6 tool steps"]
  S -->|red flag| A
  A --> L["log_entries<br/>C2 extract → C3 nutrition"]
  A --> I["save_item · end_item<br/>update_profile · set_reminder"]
  A --> V["set_planned_workouts<br/>(plan screenshot)"]
  A --> D["assess_day<br/>C5 day type"]
  A --> P["plan_sessions<br/>C6 planner + validator"]
  A --> Q["nutrition_summary · health_summary<br/>search_memory (C4)"]
  L & I & V & D --> DB[("Postgres + pgvector")]
  P --> C["Session card"] -->|"user presses<br/>Send to watch"| W["intervals.icu"] --> G["Garmin watch"]
  W -->|"hourly sync:<br/>HRV, sleep, runs, plan"| DB
  F["Uploaded notes,<br/>ChatGPT export"] --> C4["C4 facts with quotes<br/>(user confirms)"] --> DB
  A -. every call .-> T["Langfuse traces"]
```
<sub><b>Figure 2.</b> The agent decides which tools to call; each tool is an evaluated component. The only path
to the watch is the button. intervals.icu is needed because Garmin gives write access to the watch
calendar only to approved partners, and intervals.icu is one.</sub>

### 4.2 Components

| | Purpose | Input → output | Model | Key design choice |
|---|---|---|---|---|
| **C7** | Safety gate | message → `{red_flag, category, reason}` | Gemini 3.1 Flash-Lite | High recall ("when in doubt, flag"); runs in parallel, so it adds no latency |
| **C1** | Tool routing | message + context → tool calls with arguments | Gemini 3.8 Flash | It is the agent's own choice; scored separately as routing |
| **C2** | Log extractor | message + local time → events `[{kind, day, time, fields}]` | Flash-Lite | Relative dates resolved by explicit rules; sleep belongs to the morning you wake up |
| **C3** | Nutrition | meal text → items with grams, kcal, macros, 12 micronutrients | Flash-Lite | The model estimates items; totals are summed in code, negatives clamped, impossible amounts rejected |
| **C5** | Day type | watch data vs 7-day baseline, logs, items, last 14 days → class + reasons | Gemini 3.8 Flash | What the athlete *said* outweighs device numbers when they conflict |
| **C6** | Planner + validator | day type, own plan, zones, weather, request → workout with steps | Gemini 3.8 Flash + code | Every step has an exercise cue; code rejects unsafe or inconsistent plans and asks once for a fix |
| **C4** | Files | notes / ChatGPT export → facts with quotes; query → top-5 excerpts | Flash-Lite + gemini-embedding-2 | Facts wait for the user's OK; excerpts are marked untrusted |
| **C0** | Setup interviewer | known profile and items → ≤ 5 questions → filled slots | Gemini 3.8 Flash | Asks only for what's missing after the form and the files |
| **C8** | Answers | question + tool results → short answer | Gemini 3.8 Flash | Grounded in tool results, or says the data is missing |
| — | Code components | stored data → patterns, pain trend, fuel, targets, shoe km | Python | A calculation shouldn't be made up |

Every LLM output is parsed into a Pydantic model (one retry on invalid JSON). The 11 tools, their
parameters, every schema and every system prompt are in the
[appendix](appendix-prompts-and-tools.md), generated from the code.

### 4.3 One message through the system

```mermaid
sequenceDiagram
  autonumber
  actor U as Athlete
  participant App
  participant C7 as C7 safety
  participant A as Coach agent
  participant T as Tools (C2, C3, C5, C6)
  participant DB as Postgres
  U->>App: "Вчора 2 пива, спав 5 годин, зранку важка голова. На сьогодні 6 по 800. Що робити?"
  par in parallel
    App->>C7: check
    C7-->>App: no red flag
  and
    App->>DB: context: profile, items, today's logs, 14-day digest, own plan
  end
  App->>A: system prompt + context + message
  A->>T: log_entries(text)
  T->>T: C2: alcohol on Saturday, sleep 5 h on Sunday, symptom on Sunday
  T->>T: C3: 2 × 0.5 L beer = 430 kcal, 40 g alcohol (code checks limits)
  T->>DB: 3 log rows, each with Undo
  A->>T: plan_sessions("6×800 today?")
  T->>T: C5: sleep 5.2 h vs 7.1, HRV 47 vs 67, RHR 55 vs 49, beer → Recovery
  T->>T: C6: replace 6×800 m with an easy 30 min session; validator OK
  T->>DB: proposal (status: proposed)
  A-->>U: short answer in Ukrainian + session card
  U->>App: presses Send to watch
  App-->>U: workout on the intervals.icu calendar, then on the Garmin
```
<sub><b>Figure 3.</b> The main demo case. About 25–30 s and 1–2 US cents per turn, measured in Langfuse.</sub>

<p align="center"><img src="img/langfuse-extract-logs.png" width="560" alt="Langfuse trace: log_entries with extract-logs and three estimate-nutrition calls"></p>
<p align="center"><sub><b>Figure 3b.</b> A real chat turn in Langfuse (production). Left: the trace tree:
safety check, agent step, the <code>log_entries</code> tool with C2 (<code>extract-logs</code>) and one C3 call per
meal, then the answer; each with time and cost. Right: C2's input (local time + the message) and its
structured output: a 2-hour ride, two meals, all dated today.</sub></p>

<p align="center"><img src="img/langfuse-assess-day.png" width="820" alt="Langfuse trace: plan_sessions with embedding, assess-day-type and plan-workout"></p>
<p align="center"><sub><b>Figure 3c.</b> Another turn: <code>plan_sessions</code> runs a retrieval step (the embedding
call fetches <code>from_user_files</code> excerpts from an uploaded knowledge export), then C5 and C6.
C5's input is JSON (watch data, recent activities, logs, items, the 14-day digest, file excerpts);
its output is the class, a confidence and reasons with evidence. The whole turn: 16 s, $0.02.</sub></p>
<!-- MANUAL SCREENSHOT 2 (optional): a photo of the workout on the watch as img/watch.jpg, then:
<p align="center"><img src="img/watch.jpg" width="320" alt="The workout on the Garmin watch"></p>
<p align="center"><sub><b>Figure 3d.</b> After Send to watch: the workout with its steps on the Garmin.</sub></p>
-->

### 4.4 Memory: how the coach knows "your year"

The coach never sees the whole history; it sees what is relevant, from three layers:

```mermaid
flowchart TB
  subgraph ctx["Always in context"]
    P["Profile: weight, zones, sports, sleep target"]
    I["Items: goals, races, gear, injuries,<br/>medication courses, preferences (with dates)"]
    D["14-day digest: one code-written line per day<br/>(food kcal, sleep, alcohol, pain, session)"]
  end
  subgraph tools["Read on demand by tools"]
    S["health_summary / nutrition_summary:<br/>a year of synced watch data, aggregated in code"]
    R["search_memory (C4): top-5 excerpts from uploaded files"]
  end
  subgraph ingest["C4 ingest"]
    F["File (.txt .md .json,<br/>ChatGPT export ≤ 25 MB)"] --> K["Chunks of 1,400 chars,<br/>250 overlap, paragraph-aware"]
    K --> E["gemini-embedding-2, 768-d<br/>pgvector HNSW"]
    K --> X["Fact extraction with quote<br/>→ user keeps or drops"]
  end
  E --> R
  X --> I
```
<sub><b>Figure 4.</b> Lifetime goals and injuries live as editable items, recent days as a digest, the
long tail of old chats as searchable excerpts. Only the last layer is retrieval.</sub>

Halving the chunk size from 2,800 to 1,400 characters raised search recall@5 from 0.83 to 0.92
(Figure 7, right), because a person's own sentence is a small part of a long assistant answer.

### 4.5 Safety and prompt injection: defence in depth

```mermaid
flowchart LR
  X["Untrusted text<br/>(file excerpt, screenshot,<br/>tool result)"] --> W["1. Wrapped as<br/>untrusted_file_excerpts"]
  W --> R["2. Prompt rule:<br/>data, never instructions"]
  R --> K["3. Code: update_profile accepts<br/>10 fixed keys, values ≤ 200 chars"]
  K --> F["4. Facts from files are<br/>only proposed"]
  F --> B["5. Watch only via the<br/>Send to watch button"]
  B --> U["6. Every write has Undo"]
```
<sub><b>Figure 5.</b> Layers 3–6 don't depend on the model. Even if a model obeys an injected
instruction, it can't change its own instructions, can't save a file's claims as facts, and can't
put a workout on the watch.</sub>

Other guards: the safety gate on every message; a validator that blocks hard sessions on
recovery days, after injuries and on red-flag days; plausibility limits in code (a "5 kg of
sushi" meal is not saved); per-user rate limit and spending cap; guests must use their own key;
keys encrypted at rest and never sent to a model; every query scoped by user.

<table><tr>
<td><img src="img/photo-meal-message.png" width="300" alt="A message with three meal photos"></td>
<td><img src="img/photo-meal-confirm.png" width="420" alt="The coach lists items with grams and asks to confirm"><br><br>
<img src="img/langfuse-safety.png" width="420" alt="C7 output for the same message"></td>
</tr><tr>
<td colspan="2"><sub><b>Figure 5b.</b> Photos are not logged blindly. A casual Ukrainian message with three photos
(left); the coach lists what it sees with grams, splits the shared salad in half as the user said, and
asks "Усе правильно?" before calling <code>log_entries</code> (right, top). The safety gate ran on the same
message in parallel: no red flag (right, bottom).</sub></td>
</tr></table>

## 5. Data

| Data | Source, licence | Size | Why this one |
|---|---|---|---|
| Nutrition benchmark | NutriBench v2 [6], CC BY-NC-SA 4.0 | 50-meal stratified sample | A public labelled set exists, so we didn't write our own |
| Ukrainian meals | Hand-written with food-table values | 10 | NutriBench has no Ukrainian dishes |
| C1, C2, C5, C6, C7, C0, C8, injection, e2e | Synthetic, hand-written, UA/EN/mixed | 10–60 each | No public corpus of personal training logs; real chats are personal data |
| Watch data | intervals.icu API (real); a simulator for sample data and evals | 365 days per user | Checked field by field against real responses |

One data finding changed the design: intervals.icu sends heart-rate zones as a list of *upper
limits*, and the model read them as lower limits (zone 2 = 143–164 instead of 124–143). Storing
explicit ranges (`Z2: 124-143`) fixed it; a data-representation fix, not a prompt fix.

## 6. Evaluation

### 6.1 Method

- **Each component alone:** its own inputs, its own output, its own metric, so a low score
  points to one prompt or one model.
- **Metric chosen for the cost of the error:** recall for safety (a missed red flag is the
  costly error); κ for the day type (ordered, imbalanced classes); MAE in kcal for nutrition
  (the unit the user feels); first-try validity for the planner (a retry hides cost and
  latency); attack success rate for injection; database checks for the end-to-end agent.
- **Baselines** where a simple one exists (mean predictor, majority class, a watch-only rule).
- **LLM judge** only for open outputs (C6, C8, C0): Claude Haiku judging Gemini, rubric in the
  script, comments saved.
- **Uncertainty:** 95% Wilson intervals for rates [11]; repeated runs for C3 and C6 to see the
  run-to-run spread (C3: 68.8, 69.1, 71.5 kcal).
- **Traceability:** every eval case is a Langfuse trace; every result file keeps its failures.

### 6.2 Results

| Component | n | Metric | Result | 95% CI | Baseline |
|---|---|---|---|---|---|
| C7 Safety | 40 (20 flags) | recall · false alarms | **1.00** · 0.00 | 0.84–1.00 · 0–0.16 | target 1.0 |
| C1 Routing | 60 | macro-F1 · no write on a question | 0.87 · **1.00** | exact 0.68–0.88 | v2 router 0.93 |
| C2 Extractor | 43 (59 events) | (kind, day) F1 · day accuracy | **0.92** · 0.95 | – | target 0.80 |
| C3 Nutrition | 49 + 10 | kcal MAE (NutriBench · UA) | **72** · **35** | – | mean: 191 · 112 |
| C4 Facts | 24 planted | recall · precision | **1.00** · 1.00 | – | – |
| C4 Search | 24 questions | recall@5 · recall@1 · MRR | **0.92** · 0.46 · 0.60 | r@5 0.74–0.98 | 0.83 · 0.29 · 0.48 |
| C5 Day type | 30 | accuracy · κ | **0.93** · **0.91** | acc 0.79–0.98 | majority 0.33 · 0; rule 0.60 · 0.49 |
| C6 Planner | 20 | valid first try · judge 1–5 | **1.00** · 4.15 | 0.84–1.00 | v1 0.80 · 3.73 |
| C0 Interviewer | 5 simulated users | slot coverage · redundant questions | **1.00** · 0 | – | target 0.9 · 0 |
| C8 Answers | 15 | correct and grounded | **1.00** | 0.80–1.00 | – |
| Injection | 10 attacks | attack success · utility | **0.00** · 1.00 | 0–0.28 | no wrapper: 0.00 |
| End to end | 12 turns, 34 checks | cases · nothing sent without a tap | **12/12** · 12/12 | 0.76–1.00 | first run 11/12 |

<p align="center"><img src="img/fig-intervals.png" width="720" alt="Rate metrics with 95% Wilson intervals"></p>
<p align="center"><sub><b>Figure 6.</b> Small sets limit what can be claimed: 20 of 20 red flags means
recall of at least 0.84, not 1.0; 0 of 10 attacks means an attack rate of at most 0.28.</sub></p>

<p align="center"><img src="img/fig-baselines.png" width="820" alt="Components against baselines"></p>
<p align="center"><sub><b>Figure 7.</b> Every model component beats its simple baseline by a wide margin. C5's gain
over the watch-only rule comes from the text: the rule can't see alcohol, illness or pain.</sub></p>

<table><tr>
<td><img src="img/fig-c5-confusion.png" width="330" alt="C5 confusion matrix"></td>
<td><img src="img/fig-c3-scatter.png" width="380" alt="C3 estimate vs reference"></td>
</tr><tr>
<td><sub><b>Figure 8.</b> C5: both errors are "normal" called "push", one level off; no recovery
day is ever called a training day.</sub></td>
<td><sub><b>Figure 9.</b> C3 per meal. 73% of NutriBench meals within ±20%. The outliers are
unusual foods (millet flour with husks: 211 vs 679 kcal) and vague portions ("a quiche").</sub></td>
</tr></table>

### 6.3 Error analysis

- **C1 0.87 vs 0.93 for the old router.** The labels were written for a router; the agent often
  does *more* than the label (assesses the day after "slept 4 h, 6 beers"). The harmful error,
  a write tool on a pure question, never happened (1.00).
- **C2.** Errors are "ввечері" said in the morning (yesterday or today? ambiguous for people
  too) and over-extraction ("after yesterday's shawarma" logged as a meal). A review found sleep
  put on the wrong night; a prompt rule and three cases fixed it.
- **C4 recall@1 0.46.** Exports are mostly assistant text; the person's sentence is a small part
  of a chunk. Next: index only the person's own turns and add keyword search. The chunk size was
  tuned on this same set, so 0.92 is optimistic.
- **C6 specificity 3.6/5.** Targets are HR zones rather than exact paces; strength sessions are
  thin. Safety fit is the highest criterion (4.8) because hard rules are code.
- **End to end.** The first run found a real bug: the coach couldn't see race dates (item
  details weren't in its context). After the fix, 12/12.

<p align="center"><img src="img/fig-iterations.png" width="620" alt="Before and after the fixes"></p>
<p align="center"><sub><b>Figure 10.</b> Each arrow is a fix found by an eval: a validator rule (C6), a data
representation (C8), smaller chunks (C4), the race-date context (E2E).</sub></p>

**A statistical claim in the product.** The Health page shows patterns like "after alcohol your
next-morning HRV is 15% lower". The first rule (3 nights, 5% difference) produced such claims on
random data. I simulated both kinds of error and chose a Welch t ≥ 2.5 (Figure 11): false
patterns drop from about 40% to 6.5% of random 90-day logs, at the cost of finding a real 10%
HRV drop less often (43%). For a health claim, fewer false ones matter more.

<p align="center"><img src="img/fig-patterns.png" width="520" alt="Patterns threshold simulation"></p>
<p align="center"><sub><b>Figure 11.</b> The threshold trade-off, simulated in code.</sub></p>

### 6.4 Not evaluated, and why

| Part | Why | Mitigation |
|---|---|---|
| Voice transcription | Third-party model; no labelled UA/EN audio | The text lands in the box and is checked before sending |
| Photo meals, plan screenshots | Real images are personal data; no labelled set | The coach lists items with grams and asks to confirm before logging |
| C3 with a food database | Promised in the proposal, not built | LLM-only is already ~3× better than the baseline; first next step |
| Real-use accuracy | No labelled real chats yet | Next: two weeks of real use, labelled |

## 7. The product

<table><tr>
<td><img src="img/app-setup.jpg" width="400" alt="Setup step 1"></td>
<td><img src="img/app-daycard.png" width="210" alt="Day card with reasons"></td>
<td><img src="img/app-phone.png" width="200" alt="Phone view of the session card"></td>
</tr><tr>
<td><sub><b>Figure 12.</b> Setup step 1 for a new user: their own OpenRouter key, why intervals.icu
is needed, how to connect it, or sample watch data.</sub></td>
<td><sub><b>Figure 13.</b> "Why?": each reason with its evidence.</sub></td>
<td><sub><b>Figure 14.</b> The workout card on a phone.</sub></td>
</tr></table>

<table><tr>
<td><img src="img/app-training.png" width="410" alt="Training page"></td>
<td><img src="img/app-health.png" width="410" alt="Health charts"></td>
</tr><tr>
<td><sub><b>Figure 15.</b> Training: race countdown, goals with progress, the week (plan, done,
coach's suggestion), 8 weeks of volume.</sub></td>
<td><sub><b>Figure 16.</b> Health: a year of watch data, any two metrics, zoom, a click opens the day.</sub></td>
</tr><tr>
<td><img src="img/app-journal.png" width="410" alt="Journal"></td>
<td><img src="img/app-nutrition.png" width="410" alt="Nutrition"></td>
</tr><tr>
<td><sub><b>Figure 17.</b> Journal: the week against the last one, each day as labels.</sub></td>
<td><sub><b>Figure 18.</b> Nutrition: targets by day type and weight, 16 nutrients, the stated error.</sub></td>
</tr></table>

All screenshots use a synthetic athlete. The interface is in English and Ukrainian; the coach
answers in the language you write in.

## 8. Deployment, cost and access

- Cloud Run (europe-west1) behind Firebase Hosting, Neon Postgres with pgvector, secrets in
  Google Secret Manager, Langfuse for tracing, a 15-minute scheduler for sync and reminders.
- **Access:** any Google account can sign in. Members (an email list) use the app's OpenRouter
  key with a monthly cap; everyone else adds their own key in setup, validated before it's
  saved, and the code refuses every model or embedding call without it.
- **Cost:** about $0.005–0.02 per message; a full turn is 25–30 s, a log-only turn faster.
- **Tests:** 49 automated tests: sign-in on every route, a two-user isolation test on every
  endpoint, CSRF, encryption, budget and guest keys, validator, patterns. Details:
  [06-deployment.md](06-deployment.md).

## 9. What I learned

1. **Split the problem until each part can be measured.** "The coach is good" can't be
   evaluated; "sleep goes on the morning you wake up" can. The agent works because its tools are
   small enough to score alone.
2. **The cheapest fix is often in the data, not the prompt.** HR zones as upper limits, race
   dates missing from the context: both "model errors" were representation errors.
3. **Give numbers to code and language to the model.** Totals, limits, date arithmetic,
   validation and statistics are deterministic; the model reads text, picks tools and explains.
   This also made safety *checkable*.
4. **Temporal normalisation is the hardest NLP part of a diary.** "Вчора ввечері" said at 09:30,
   "спав 5 годин" after "вчора 2 пива": the errors are about time, not about entities.
5. **An agent trades measurability for flexibility.** Moving from a router to an agent lowered
   the routing score (0.93 → 0.83–0.87 across runs) but handled open requests (gear, screenshots, week plans).
   Re-scoring it as tool routing, plus an end-to-end eval in the database, recovered most of
   what was lost.
6. **Small eval sets need intervals, and statistical claims in a product need tests.** 20/20 is
   "at least 0.84". The same honesty applies to features: the patterns card needed a
   significance threshold chosen by simulation.
7. **Prompt injection is a systems problem.** The model resisted all 10 attacks with or without
   the wrapper, so the set is too easy to show what the wrapper adds; the guarantees that matter
   are the ones that don't need the model to behave.
8. **An AI coding assistant needs rules and checks, not just prompts.** It drifted (stale docs,
   claims of "done" without checks) until AGENTS.md defined "done" and every failure became a
   test (section 11).

## 10. Limitations and future work

**Limitations:** eval sets are small (10–60 cases), synthetic, written with the coding assistant
and labelled by one annotator; vision and voice are not measured; intervals.icu is required for
real watch data; the LLM judge is a model.
**Next:** label two weeks of real use and re-run C1, C2, C5; ground C3 in a food database (the
ablation from the proposal); a vision set of plan screenshots and meals; a morning notification
with Send / Keep buttons; a coach mode where a human coach approves the AI's proposals.
Workflows: [plan 09](../plans/09-next-version.md).

## 11. How the AI coding assistant was used

Claude Code wrote most of the code under [AGENTS.md](../../AGENTS.md): project, grading
criteria, CRISP-DM, security rules, and a definition of done (code runs, eval result recorded,
"verified / not verified" stated). Skills: `/plan`, `/implement`, `/explain`, `/eval`,
`/ui-check`, and the official Langfuse skill. Nine plans in [docs/plans](../plans/) record each
iteration. Every real failure became a rule, validator, test or eval case; the table and an
honest list of what the assistant did badly are in [07-agentic-coding.md](07-agentic-coding.md).

## 12. CRISP-DM

```mermaid
flowchart LR
  B["1 Business<br/>understanding"] --> DU["2 Data<br/>understanding"] --> DP["3 Data<br/>preparation"] --> M["4 Modeling"] --> E["5 Evaluation"] --> DEP["6 Deployment"]
  E -.->|"v1 → v2: validator, zones"| M
  DEP -.->|"v3: daily use → agent"| B
  DEP -.->|"v4–v5: usability"| M
  E -.->|"v6: review, e2e, intervals"| M
```
<sub><b>Figure 19.</b> Six rounds (v1–v6), each started by an eval or by using the app.</sub>

| Phase | Main result | File |
|---|---|---|
| 1 | Problem, users, success criteria; intervals.icu as the only write path to Garmin | [01](01-business-understanding.md) |
| 2 | Real API responses checked; zones as upper limits; Garmin Coach plans don't reach intervals.icu | [02](02-data-understanding.md) |
| 3 | Eval sets, NutriBench sample, chunking | [03](03-data-preparation.md) |
| 4 | Components, prompts, pipeline → agent | [04](04-modeling.md) |
| 5 | Per-component evals, baselines, intervals, e2e, injection | [05](05-evaluation.md) |
| 6 | Cloud Run, open sign-up with own keys, sample data | [06](06-deployment.md) |

## References

1. Yao, S. et al. ReAct: Synergizing Reasoning and Acting in Language Models. ICLR 2023.
2. Schick, T. et al. Toolformer: Language Models Can Teach Themselves to Use Tools. NeurIPS 2023.
3. Lewis, P. et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS 2020.
4. Greshake, K. et al. Not What You've Signed Up For: Compromising Real-World LLM-Integrated
   Applications with Indirect Prompt Injection. AISec 2023.
5. Zheng, L. et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS 2023.
6. Hua, A. et al. NutriBench: A Dataset for Evaluating Large Language Models on Nutrition
   Estimation from Meal Descriptions. arXiv:2407.12843.
7. Plews, D. J. et al. Training Adaptation and Heart Rate Variability in Elite Endurance
   Athletes. Sports Medicine 43, 2013.
8. Banister, E. W. et al. A systems model of training for athletic performance. Australian
   Journal of Sports Medicine 7, 1975.
9. Mifflin, M. D. et al. A new predictive equation for resting energy expenditure in healthy
   individuals. American Journal of Clinical Nutrition 51, 1990.
10. Jeukendrup, A. A step towards personalized sports nutrition: carbohydrate intake during
    exercise. Sports Medicine 44, 2014.
11. Wilson, E. B. Probable inference, the law of succession, and statistical inference. JASA 22, 1927.
12. Cohen, J. A coefficient of agreement for nominal scales. Educational and Psychological
    Measurement 20, 1960.
13. Chapman, P. et al. CRISP-DM 1.0: Step-by-step data mining guide. 2000.

**Reproduce:** `uv run python -m evals.run_all`, `uv run python -m evals.run_e2e`,
`uv run python -m evals.stats`, `uv run python docs/report/make_figures.py`,
`uv run python docs/report/make_appendix.py`.
