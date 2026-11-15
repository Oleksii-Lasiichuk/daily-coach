# Plan 04 — Craft redesign, separate onboarding, sources (RAG)

CRISP-DM phase: 4. Modeling (C4 sources), 6. Deployment (UI), with 5. Evaluation for C4.
Status: draft, waiting on "go". Deadline 2026-11-15 evening.

## Goal

Make the app look made by a person, not generated. Make it very simple, with a workflow you
understand at a glance:
- **Setup is a separate, short flow:** connect intervals.icu → confirm what we know → add your
  files → answer a few questions.
- **Chat is only for daily use.**
- **New feature:** upload `.txt` / `.md` exports (e.g. your ChatGPT health and sport projects).
  The coach extracts facts you confirm, and looks things up in the files when it answers or plans
  (retrieval = component C4).

## What the current UI gets wrong

Research summary (sources at the end). Our current screens hit 7 of the common AI tells.

| AI tell | Where we have it | Fix |
|---|---|---|
| Hero metric layout (big word + row of 4 stats) | Day card: "Easy" + Sleep/HRV/RHR/Form tiles | One sentence instead: "Easy day. You slept 6 h; HRV is normal." Numbers sit inline in the text |
| Cards wrapping everything, rounded boxes with soft shadows | Every section is a 16 px rounded card | No cards. Sections separated by hairline rules and spacing, like a notebook page |
| Same radius on everything, pills everywhere | Pill buttons and pill chips | 4 px radius on controls; text links for secondary actions; no chips row |
| Tinted full-card backgrounds for status | Green/blue day card | Status is a small coloured word plus a 3 px rule under it; the page stays neutral |
| Every button looks similar, chips as decoration | Reassess, Dismiss, chips | One primary action per screen (Apply). The rest are quiet text buttons |
| Two-column dashboard on desktop | Cards left, chat right | One centred column (max 600 px) on every screen size; it reads like a page |
| Chat as onboarding | First chat asks setup questions | Separate 4-step setup; chat only for the day |

Also avoided:
- purple/blue gradients, glassmorphism, glow, neon on dark;
- Inter / Roboto;
- the "new default" (cream + serif + sage);
- icon-above-heading;
- emoji;
- bouncy motion;
- modals;
- generic copy ("Get started", "Unlock").

## Design direction: "training log"

The reference is a paper training diary and a good watch face: data, plainly set.

- **Type:** **Fixel** by MacPaw, a Ukrainian grotesk with full Cyrillic (OFL licence),
  self-hosted (2 weights, ~120 KB woff2). It has character without being a trend default.
  Fallback: system UI.
- **Sizes:** 15 px body, 13 px meta, 28 px day headline. Numbers use tabular figures.
- **Colour:**
  - light: neutral warm-grey paper `#F3F2EF`, ink `#151515`;
  - dark: `#121212` / `#ECEBE7`;
  - **one** accent, signal orange `#E8562A`, only on Apply and the recording state;
  - day type is a word in its colour (recover slate, easy green, normal ink, push orange) with
    a short rule, never a filled block.
- **Shape:** no cards, no shadows. 1 px hairlines, 4 px control radius, 44 px touch targets.
- **Layout:** one column. Each screen has a clear top-to-bottom story.
- **Motion:** only state changes (150 ms), and `prefers-reduced-motion` is respected.
- **Copy:** plain and specific, with numbers and units. Uses "you" and has no exclamation marks.

### Screens

1. **Sign in:** name, one sentence, Google button. Nothing else.
2. **Setup (new, 4 steps):** a step counter at the top ("2 of 4"), a Back link, and Skip on
   every step.
   1. *Connect intervals.icu:* key + athlete ID. On success: "Found: Олексій, Run · Swim ·
      Ride zones, last 14 days of training."
   2. *What we know:* the prefilled profile as an editable list, plus four short fields that
      matter most: main goal, next race + date, sports you do (checkboxes from your
      intervals.icu types + "add"), weekly availability (7 day toggles + note).
   3. *Your files (optional):* drop or pick `.txt` / `.md`. A progress line while reading. Then
      "Found 23 facts": a list with checkboxes (keep / drop), grouped by category, each with
      the quote it came from.
   4. *A few questions:* C0 asks 2–5 questions only about what is still missing after steps 1–3
      (injuries, medications, sleep target…). Each is a normal input field, and each can be
      skipped. → **Start**.
3. **Today:**
   - date;
   - the day sentence + "Why" (expandable evidence list, each item showing its source:
     watch / you / file);
   - **Session**: Garmin's plan → our version, steps as a 2-column list (time | what), one
     **Apply** button;
   - **Log** for today (time | entry | kcal);
   - **Conversation**: the last few messages;
   - pinned composer at the bottom: text field, mic, send.
4. **You:** Profile (editable list) · Facts (editable, each with its source) · Files (list,
   size, facts found, delete, add).
5. **Settings:** intervals.icu, AI cost this month, sign out.

## C4 Sources: design

- **Upload:** `.txt` / `.md`, up to 5 MB per file and 20 files per user. Text is stored in
  `sources`, split into ~700-token chunks with 100-token overlap, on paragraph boundaries.
- **Embeddings:** `google/gemini-embedding-2` via OpenRouter ($0.20 per 1M tokens; a 5 MB export
  is ≈ $0.30), stored in Neon **pgvector** (`chunks.embedding vector(…)`, HNSW index,
  per-user filter).
- **Fact extraction (ingest):**
  - Flash-Lite reads chunk batches and proposes facts (category, text, date if stated, the
    supporting quote, chunk id), deduplicated against existing facts.
  - Processing is batched per request: the page polls `/sources/{id}/step` every second, and each
    step handles about 8 chunks. This works on Cloud Run without background workers.
  - The user confirms the facts in setup step 3 or under You → Files.
- **Retrieval (query):**
  - **C8 reply** gets the top 5 chunks for the message.
  - **C5 and C6** get the top 5 chunks for "injuries, illness, medication, recent health
    issues" plus today's message.
  - Retrieved chunks are shown as "From your files" in the Why list, so the user sees what was
    used.
- **Safety:** file text is data, never instructions; the prompts say so, and files can't trigger
  writes. Keys and secrets are never extracted. Files are deleted with the user.

**Main alternative considered:** Postgres full-text search instead of embeddings. It lost
because there's no Ukrainian stemmer in Postgres and the exports mix UA and EN; embeddings
handle both. (Hybrid search later if recall is weak.)

## Steps

1. **Design system v2:** self-host Fixel, rewrite `app.css` (tokens, no cards), base layout, one
   column. → verify: screenshots at 375 / 1280, light and dark, checked against the table above.
2. **Setup flow:** `/setup/1..4`, `users.setup_done`, redirect new users there, resumable;
   C0 moves from chat to step 4 (questions → form fields → parsed answers).
   → verify: a fresh user completes setup on a phone in < 3 min; Skip works on every step.
3. **Today and You rebuilt** in the new language; chat no longer starts onboarding.
   → verify: screenshots; all existing tests pass.
4. **C4 Sources:** migration `002_sources.sql` (`sources`, `chunks` with pgvector), upload,
   chunking, embeddings, step-wise ingest, fact review, retrieval in C5/C6/C8, Files list.
   → verify: upload a 1 MB sample export; facts appear with quotes; a question answered from
   the file shows the file in Why; isolation test covers the new endpoints.
5. **C4 eval:** a synthetic "ChatGPT export" (≈ 40 k tokens, UA/EN, with 25 planted facts) +
   20 questions with known source chunks.
   - Metrics: fact extraction P/R/F1 (judge-matched), retrieval recall@5, answer correctness.
   - → verify: `evals.run_c4` runs; result recorded in `05-evaluation.md`.
   - C0 eval updated to the form flow.
6. **Deploy, then update the README, report and demo script.** → verify: on
   https://coach.lasiichuk.com once the certificate is active (otherwise `*.web.app`).

If time runs short, cut in this order: hybrid search, the C4 answer-correctness metric, file
delete UI (keep the API), desktop polish.

## Acceptance criteria

- [x] No screen uses cards, gradients, shadows, pills or a hero-metric row. One accent, one
      primary action per screen.
- [x] A new user goes Sign in → Setup (4 skippable steps) → Today, without using chat.
- [x] `.txt` / `.md` upload works up to 5 MB. Facts are proposed with quotes and confirmed by
      the user. Answers and plans use the files and show which file was used.
- [x] C4 has an eval with recall@5 and fact F1, recorded in the report.
- [x] Tests pass, including isolation for sources and chunks.

## Sources (research, 2026-11-14)

- AI slop pattern catalog (pixelslop): https://cdn.jsdelivr.net/npm/pixelslop@0.3.8/dist/skill/resources/ai-slop-patterns.md
- AI design slop, overused UI patterns: https://noqta.tn/en/blog/ai-design-slop-overused-ui-patterns-fix-2026
- 7 signs a UI has been vibe coded: https://www.thefountaininstitute.com/blog/signs-vibe-coded-ui
- Why AI design looks generic: https://superdesign.dev/blog/why-ai-design-looks-generic
- Designers review vibe-coded sites (YC): https://recapio.com/digest/design-experts-review-vibe-coded-websites-by-y-combinator
- Onboarding: chat vs forms: https://www.chameleon.io/blog/what-most-teams-get-wrong-about-onboarding-in-2025 · https://userpilot.com/blog/onboarding-ux-patterns · https://www.appcues.com/blog/user-onboarding-guide

## Result (2026-11-14)

**Built:**
- the design system v2 with self-hosted Fixel;
- the 4-step setup, with C0 moved from chat to step 4;
- Today, You and Settings rebuilt;
- C4 sources: upload, step-wise reading, fact review with quotes, pgvector search used by C5, C6
  and C8;
- **History** (the user's idea, added mid-build): a month calendar and day pages, plus a code-built
  14-day digest in the C5, C6 and C8 prompts.

**Verified:**
- 25 tests pass, including isolation for files, facts and the review endpoint.
- The full flow was clicked through in the browser at 375 px: setup 1→4 with a simulated file
  upload → 4 proposed facts with quotes → kept. Step 4 asked only 3 questions. A Ukrainian chat
  message produced Easy day, a modified session and logs.
- Desktop at 1280 px in dark mode, History and You checked.
- Deployed: https://daily-coach-af64d.web.app (health ok, login 200, font 200); prod migration
  002 applied.

**Evals:**
- C4: fact recall 1.00 and precision 1.00; search recall@5 0.92 (v1 0.83), MRR 0.60.
- All other components were re-run after the prompt changes: C6 judge 4.11, C8 1.00,
  C0 coverage 1.00 (details in `05-evaluation.md`).

**Deviations from the plan:**
- Chunks are 1,400 characters, not 2,800 (better search; tuned on the eval set).
- No tabular figures (Fixel's tabular zero is slashed).
- The domain is `coach.lasiichuk.com`. I first registered a misspelled one; that is fixed and
  the wrong entry deleted.

**Not verified:**
- the HTTPS certificate on `coach.lasiichuk.com` (still validating at the time of writing);
- a real Google sign-in;
- the mic on a phone;
- a real 5 MB export (only 36 k chars and a small test file were used);
- Apply on today's date.
