# 06 — Deployment

CRISP-DM phase 6.

- **Live:** https://coach.lasiichuk.com (custom domain via Firebase Hosting; Ivan added a CNAME at
  GoDaddy) and https://daily-coach-af64d.web.app.
- **Local:** see the README.

```
Browser ─► Firebase Hosting (TLS, CDN) ─► Cloud Run "coach" (europe-west1, 0–2 instances)
                                            ├─ Neon Postgres (branch production; dev = main)
                                            ├─ intervals.icu (per-user key, Fernet-encrypted)
                                            └─ OpenRouter ─► Langfuse traces
```

## Security

- **Sign-in:** Google sign-in through Firebase Auth. The server checks the token against
  Google's public keys, requires a verified email and an email on the allowlist, and keeps
  only the user ID in a signed `__session` cookie (`HttpOnly`, `Secure`, `SameSite=Lax`).
- **Routes:** every route requires a session; a test walks all routes. Every query is scoped
  by user; a two-user test hits every endpoint. POSTs need a matching `Origin` (CSRF).
- **Secrets:** prod values live in Google Secret Manager, read by the Cloud Run service
  account. Users' intervals.icu keys are encrypted at rest; only the last 4 characters are
  ever shown. Keys are never sent to an LLM.
- **Work vs personal accounts:** `scripts/gc` uses a separate gcloud config, so this project
  can never use the author's work Google Cloud account.

## v4 changes (2026-11-15)

- **Sync:** intervals.icu is synced at most hourly per user, by the 15-minute tick and when a
  page opens, so Today shows fresh data through the day.
- **Admin:** hosting limits, console links, database size and the app key's credit are shown
  only to the emails in `ADMIN_EMAILS`. Other users see only their own cost.
- **UI language:** English or Ukrainian per user (`user_prefs.lang`, migration 005). Only the
  app's own words are translated (`app/i18n_uk.json`); chat and data are not.
- **Files:** up to 25 MB (Cloud Run's request limit is 32 MB). A ChatGPT export with more than
  30 chats keeps only the chats about sport, health and food, at most 4,000 parts per file.
- **Push answers:** the morning and evening notifications have buttons (slept badly / OK /
  great). The service worker posts the answer, and it's logged without opening the app
  (Android and desktop; iPhone shows no buttons).

## AI security (v5 review, 2026-11-15)

The rules come from treating every model output and every file as untrusted:

| Risk | What stops it (in code, not only in the prompt) |
|---|---|
| Prompt injection from files | File search results are wrapped as untrusted text; facts from files are only *proposed* until you keep them; the injection eval has 0/10 successes |
| The model rewriting its own instructions | `update_profile` takes 10 fixed keys; values are capped at 200 characters; instructions are edited only by you |
| The model acting on your watch | Nothing reaches intervals.icu or Garmin without your **Send to watch**; the validator checks zones and duration in code |
| Another user's data | Every query is filtered by `user_id`; tests open every page and detail sheet as a second user |
| Impossible or joke amounts ("5 kg of sushi", "5 L of vodka") | `implausible()` rejects an entry above physical limits (4,000 kcal, 3 kg, 150 g alcohol, 1,000 mg caffeine, sleep 0–16 h, pain 0–10) before it's saved; the coach then asks for the real amount and treats extreme alcohol as a safety concern. Manual edits are capped the same way |
| Model numbers out of range | Nutrition totals are summed in code; negative values become 0; every structured output is a Pydantic model |
| XSS through model text | Replies are HTML-escaped before the light Markdown; no links or HTML from the model are rendered |
| Cost runaway | A $20 monthly cap per user on the app key, 30 messages per 10 minutes, max 6 tool steps per message, 4 images of 4 MB, 4,000 characters per message |
| Secrets | Keys are encrypted at rest, never logged, never put into a prompt; admin pages are for `ADMIN_EMAILS` only |

## Cost

| Item | Monthly cost |
|---|---|
| Cloud Run, Firebase Hosting, Neon (free tier), Langfuse (free tier) | $0 |
| LLM, 2 users | ≈ $2–6 by the measured cost per turn |

## How the system was built

- **AI coding assistant:** Claude Code was steered by `AGENTS.md` and three short skills
  (`/plan`, `/implement`, `/explain`). The official Langfuse and Neon agent skills were added
  for tracing and the database.
- **Plans:** each step was planned in `docs/plans/` and checked with a "verify" command before
  moving on.

## v6 changes (2026-11-15)

- **Sample watch data.** Anyone without Garmin or intervals.icu can choose it in setup: their
  account is connected to a simulated intervals.icu athlete (`app/demo.py`): wellness and
  activities generated from the date, an in-memory calendar for "Send to watch", no network.
  The same simulated athlete is used by the end-to-end eval. A local `/demo-login` existed
  briefly in v6 and was removed: the deliverable is the deployed app.
- **Open sign-up (`OPEN_SIGNUP=true` in production).** Any verified Google account can sign
  in. People on `ALLOWED_EMAILS` are members and use the app's OpenRouter key with a monthly cap.
  Everyone else is a guest: `llm.check_budget` refuses every model and embedding call until the
  guest saves their own key (validated against OpenRouter's free key-info endpoint, stored
  encrypted). Setup step 1 asks for it. Guests without Garmin can choose **sample watch data**:
  their account is connected to the simulated athlete, so nothing reaches a real watch. Tests:
  `tests/test_open_signup.py`. Risk left: guests' rows and files use our Neon storage.
