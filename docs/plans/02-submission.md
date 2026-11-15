# Plan 02 — Submission build (deadline 2026-11-15, evening)

CRISP-DM phases: 4. Modeling, 5. Evaluation, 6. Deployment (1–3 are done in the report).
Status: draft, waiting on "go".
Replaces milestones 1–5 for the submission. `01-foundation.md` keeps the full design
(security, data model, screens); this plan says what of it is built by the deadline.

## Goal

By tomorrow evening:
- a working app, locally and at a public URL, that you and your brother sign in to;
- one chat that logs the day and adapts training, with every NLP component evaluated;
- a report and a demo video of at most 10 minutes.

## Decisions from your answers (2026-11-14)

| Topic | Decision |
|---|---|
| Subdomain | Ask Ivan (question 0 in the `docs/setup.md` message). The submission uses `https://daily-coach-af64d.web.app`; the custom domain is added when he answers. |
| Language | English UI. Chat and stored facts can be Ukrainian, English or mixed. |
| Look | Modern, in the spirit of Monobank, Strava (2025–26) and Nova Poshta: bold numbers, rounded cards, one orange accent. `docs/design-guidelines.md` Part B is updated to match. |
| Frontend | Server-rendered (FastAPI + Jinja + HTMX, a little vanilla JS). Cheapest and fastest to build; no separate build step. |
| Sports | Not hard-coded. Activity types come from intervals.icu (Run, Swim, Ride, WeightTraining, Badminton, …). Preferences and goals are free text plus a per-user list of sports. The coach works for running, swimming, cycling and anything else. |
| Rhythm | Used through the day. Phone notifications and reminders (e.g. medication times set by a doctor) come after the submission as web push; the extractor already records illness and medication events so reminders can use them later. |
| Base plan | Garmin Coach stays. The AI reads the planned workouts in intervals.icu and proposes extra or replacement sessions; they may overlap with Garmin Coach. |
| Profile fields | Not fixed up front. The onboarding interviewer (C0) asks for what is missing. |
| Brother | Same features. You pay for everything; no per-user budget page, just a safety cap per user. |
| Brother's privacy | Honest limit: whoever runs the server and holds the keys can read the data, because the LLM needs plaintext. We make it hard to see by accident: no admin screen of other users, his intervals.icu key is encrypted, and logs and traces show `user_id` only, not the email. Encrypting all his text at rest is planned after the submission. |
| Repo | Clean and public for the submission, private afterwards. No personal data in git. Eval sets are synthetic test cases written for this purpose, not mock users. |

## Architecture change: simpler, safer auth

Before: firebase-admin session cookies, which need Google credentials locally (application-default
credentials, which would collide with your work gcloud).

Now:
1. The browser signs in with Firebase JS (Google popup) and POSTs the ID token to `/auth/session`.
2. The server verifies the token against Google's public keys with `google-auth`
   (`verify_firebase_token`, audience `daily-coach-af64d`). This needs no credentials.
3. It checks `email_verified` and the allowlist, then sets its own signed cookie `__session`
   (Starlette `SessionMiddleware`, `HttpOnly`, `Secure`, `SameSite=Lax`, 14 days).

This means one dependency fewer, no Google credentials on your laptop, and the rest of the
01-foundation auth rules stay as they were (deny by default, Origin check).

## Scope by the deadline

In:
- Scaffold, Neon DB plus migrations, Google sign-in with the allowlist, two-user isolation tests.
- Connect intervals.icu (key encrypted). Read the athlete, sport settings and zones, wellness (sleep,
  HRV, resting HR), recent activities and planned events.
- **Today** screen: today's day type, planned workouts, today's logs, suggestion chips, and the chat.
- **About me** screen: profile fields and facts, editable, each marked with its source
  (intervals / you / AI).
- NLP pipeline (components from `docs/report/01-business-understanding.md`):
  - C7 Safety gate → C1 Router → C2 Log extractor → C3 Nutrition estimator → saved logs
  - C5 Day-type assessor → C6 Plan adapter + code validator → **Apply** → intervals.icu event
    → Garmin
  - C0 Onboarding interviewer: the first chat reads what is known and asks for the gaps
  - Memory (minimal C4): a `facts` table (e.g. "left knee pain since Oct", "goal: Lviv half
    in April"), written by C0/C2 and editable in About me, and used as context by C5 and C6.
- One eval script and one result per component, recorded in `docs/report/`.
- Deploy: Cloud Run + Firebase Hosting (`*.web.app`).
- Report and demo script.

After the submission:
- Full history wiki and the ChatGPT import
- Notifications and reminders (web push)
- Custom domain
- Gear mileage
- Weight log charts
- Encrypting all text at rest
- Streaming replies

## Evaluation by the deadline

Eval sets are small, synthetic and hand-checked. They are written by the LLM from a list of
situations, then corrected by you, so the labels are yours. They contain no personal data.

| Component | Set | Metric |
|---|---|---|
| C7 Safety | 40 messages, half red flags, UA/EN | recall (target 1.0), false-alarm rate |
| C1 Router | 60 messages, multi-label | macro-F1 |
| C2 Extractor | 50 messages with gold events and dates | field-level P/R/F1, date accuracy |
| C3 Nutrition | 50 meals from NutriBench (public) + 15 Ukrainian meals | kcal and carbs MAE |
| C5 Day type | 30 day scenarios (wellness + logs) with your label | accuracy, Cohen's κ; baseline = rule on HRV and sleep only |
| C6 Plan adapter | 20 scenarios | validator pass rate, rule violations, LLM-judge rubric (5 checked by hand) |
| C0 Interviewer | 5 synthetic athletes with hidden profiles, simulated user | slot coverage, redundant questions |

Low scores get a short "why and how to improve" note in the report, as the assignment asks.

## Steps (time boxes are a target, not a promise)

Tonight:
1. Scaffold, config, `/healthz`, tests (1 h)
   → verify: `uv run pytest`; `curl localhost:8000/healthz`.
2. DB: `001_init.sql` (users, user_secrets, profiles, facts, logs, chat_messages, proposals,
   llm_usage, audit_log) on the Neon dev branch (45 min)
   → verify: migrate twice, the second run applies nothing.
3. Auth plus the protected-routes and isolation tests (1.5 h)
   → verify: tests pass; real Google login on localhost.
4. intervals.icu client plus connect screen; save one real response as a fixture with secrets
   removed (1.5 h)
   → verify: connect shows your name; the key is not in logs.
5. Layout plus Today and About me screens in the design system (2 h)
   → verify: screenshots at 375/1280, light and dark.

Sunday morning:
6. LLM wrapper (OpenRouter, Pydantic output, retry once, Langfuse, cost cap), then C7, C1, C2,
   C3 wired into the chat (3 h)
   → verify: a UA/EN message produces saved logs with correct dates.
7. C5, C6, validator, proposal card, Apply, Undo (3 h)
   → verify: "I drank 4 beers and slept 5 h" → recover day → proposal → Apply → visible
   in intervals.icu.
8. C0 onboarding chat (1 h)
   → verify: a fresh user gets questions only about missing fields.

Sunday midday:
9. Eval sets plus scripts plus results (3 h; you review the labels, ~30 min)
   → verify: `uv run python -m evals.run_all` prints the table; results are in `docs/report/`.

Sunday afternoon:
10. Deploy to Cloud Run plus Firebase Hosting (1 h)
    → verify: login works on your phone at `*.web.app`.
11. README, report phases 2–6, demo script; you record the video (2 h).

## What you do, and when

- Now: `docs/setup.md` sections 1–7: Firebase Auth, Neon, OpenRouter, Langfuse, intervals.icu key,
  `.env`. Then send Ivan the message from section 8.
- Tonight, after step 3: a real Google login on localhost (1 min).
- Sunday midday: review the eval labels (~30 min).
- Sunday afternoon: record the demo video.

## Risks

- **Time:** if late, cut in this order: C0 → Undo → deploy (local run is what grading needs) →
  Ukrainian meals in the C3 set.
- **intervals.icu field names:** checked against a real response before coding (S9).
- **Garmin Coach workouts may not appear in the intervals.icu calendar.** If not, C6 plans
  from the intervals.icu calendar plus your words ("Garmin wants 8×400 today"). Checked in step 4.
