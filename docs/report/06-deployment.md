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
