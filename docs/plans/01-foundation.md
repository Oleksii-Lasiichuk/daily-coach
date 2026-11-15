# Milestone 1 — Foundation

CRISP-DM phase: 6. Deployment (skeleton first), with 1. Business understanding refined.
Status: full design, built after the submission. For the 2026-11-15 deadline, `02-submission.md`
says what is built; its decisions (auth without firebase-admin, generic sports, look) override this file.
Related: `docs/report/01-business-understanding.md`, `docs/design-guidelines.md`, `docs/setup.md`.

## Goal

A real, hosted, secure base that every later NLP component plugs into. At the end of M1, I
(and my brother) can open `https://coach.lasiichuk.com` on phone or laptop, sign in with Google,
connect intervals.icu, see and edit our profile, gear and goals (mostly prefilled from
intervals.icu), and chat with an assistant that already knows that profile.

M1 has no NLP components to evaluate yet. Its "evaluation" is automated tests for the
security invariants plus a manual checklist. Building the hosting and auth first means every
later component is demoed on the real app, not a notebook.

## Scope

In:
- Repo scaffold, local dev, tests, deploy to Cloud Run behind Firebase Hosting, custom domain.
- Google sign-in (Firebase Auth), server-side email allowlist, `__session` cookie, sign out.
- Per-user data model and migrations; two-user isolation.
- Connect intervals.icu: API key + athlete ID, test call, encrypted storage, disconnect.
- About me: profile (prefilled from intervals.icu where possible), weight log, gear, goals/races.
- Onboarding v1 (forms, 3 skippable steps). The AI interview (C0) comes in M2.
- Today screen with chat v1: one LLM call with the profile in context, non-streaming,
  per-user budget, usage recorded, Langfuse trace.
- Design system v1 and the screens listed below.

Out (later milestones): ChatGPT import, history wiki, AI interview, log extraction, nutrition,
day type, plan changes, writing to intervals.icu, daily job, Garmin Personal API.

## Assumptions (change if your answers differ)

- Subdomain `coach.lasiichuk.com`.
- English UI; chat in any language (UA/EN/mixed).
- Server-rendered pages (Jinja + HTMX), no SPA build.
- Default time zone `Europe/Kyiv`; metric units; pace in min/km, swim pace in min/100 m.
- Two allowlisted emails: mine and my brother's. Monthly LLM budget of $5 each.
- Region: Cloud Run `europe-west1` (Belgium); Neon `aws-eu-central-1` (Frankfurt), ~10 ms apart.

## Design

### Request path

```
Browser (phone/laptop)
  → https://coach.lasiichuk.com            Firebase Hosting (TLS, CDN for /static)
  → rewrite "**" → Cloud Run "coach"      FastAPI app (scale 0..2)
       ├─ Firebase Admin SDK              verify ID token / session cookie
       ├─ Neon Postgres                   all app data
       ├─ intervals.icu API               read athlete, zones, gear (per-user key)
       ├─ OpenRouter                      LLM (shared key, per-user budget)
       └─ Langfuse                        traces of LLM calls
```

Known constraints of Firebase Hosting → Cloud Run:
- Only the cookie named `__session` reaches Cloud Run; all others are stripped.
- The Cloud Run service must allow unauthenticated invocations (the app does auth itself).
- The proxy has a request timeout (reported around 60 s), and streaming responses may be
  buffered. So chat v1 is non-streaming with a "thinking" indicator, and each LLM call has a
  30 s timeout. Step 11 tests streaming; if it works, we can switch later.

### Sign-in flow

1. `/login` shows "Continue with Google" (Firebase JS SDK, popup on desktop, redirect on mobile).
2. The browser gets a Firebase ID token and POSTs it to `/auth/session`.
3. The server verifies the token, requires `email_verified`, and checks the email against
   `ALLOWED_EMAILS`. Not allowed → 403 page "This app is private", nothing stored.
4. It upserts `users`, creates a Firebase session cookie (14 days), and sets it as `__session`
   (`HttpOnly; Secure; SameSite=Lax; Path=/`).
5. Every request: the `current_user` dependency verifies the cookie (with revocation check)
   and loads the user. No cookie or invalid → redirect to `/login` (HTML) or 401 (HTMX/JSON).
6. `/auth/logout` (POST) revokes refresh tokens and clears the cookie.
7. POST requests must carry an `Origin` header equal to the app origin (CSRF guard).

### Data model (migration `001_init.sql`)

All tables with personal data have `user_id uuid not null references users(id) on delete cascade`.

| Table | Key columns |
|---|---|
| `users` | `id`, `firebase_uid` (unique), `email` (unique), `display_name`, `time_zone`, `onboarding_step`, `monthly_budget_usd`, `created_at` |
| `user_secrets` | `user_id`, `provider` (`intervals`), `ciphertext`, `last4`, `external_id` (athlete ID), `created_at`; PK (`user_id`, `provider`) |
| `profiles` | `user_id` (PK), `birth_year`, `sex`, `height_cm`, `resting_hr`, `max_hr`, `lthr`, `hr_zones` (jsonb), `run_threshold_pace_s_per_km`, `pace_zones` (jsonb), `swim_css_s_per_100m`, `weekly_availability` (jsonb), `field_sources` (jsonb: field → `intervals` / `user` / `ai`), `updated_at` |
| `weight_log` | `id`, `user_id`, `measured_on`, `kg`, `source` |
| `gear` | `id`, `user_id`, `kind` (`shoes`/`bike`/`other`), `name`, `started_on`, `distance_km`, `retire_at_km`, `retired`, `source`, `external_id` |
| `goals` | `id`, `user_id`, `kind` (`race`/`goal`), `title`, `target_date`, `sport`, `distance_m`, `priority` (A/B/C), `target`, `status` |
| `chat_messages` | `id`, `user_id`, `role`, `content`, `trace_id`, `created_at` |
| `llm_usage` | `id`, `user_id`, `component`, `model`, `input_tokens`, `output_tokens`, `cost_usd`, `created_at` |
| `audit_log` | `id`, `user_id`, `actor` (`user`/`ai`/`system`), `action`, `entity`, `entity_id`, `before` (jsonb), `after` (jsonb), `created_at` |

`audit_log` exists from day one: every AI change in later milestones must be traceable and revertible.

### Code layout

```
app/
  main.py          app factory, routers, middleware (request id, Origin check)
  config.py        settings from env, validated at startup (fail fast if missing)
  auth.py          Firebase verify, allowlist, session cookie, current_user
  db.py            psycopg pool, small query helpers
  migrate.py       applies migrations/*.sql in order
  crypto.py        encrypt/decrypt user secrets (Fernet, key from env/Secret Manager)
  intervals.py     intervals.icu client: get_athlete, get_sport_settings, get_gear
  llm.py           OpenRouter call, budget check, usage record, Langfuse trace
  profile.py       profile/gear/goals reads and writes (all take user_id)
  routes/          pages.py, auth.py, onboarding.py, profile.py, chat.py, settings.py
  templates/       base.html + one template per screen + partials for HTMX
  static/          css/tokens.css, css/app.css, js/auth.js, icons/, manifest.webmanifest
migrations/        001_init.sql
tests/             test_auth.py, test_isolation.py, test_routes_protected.py,
                   test_crypto.py, test_intervals.py (fixtures), test_budget.py
Dockerfile, firebase.json, .firebaserc, pyproject.toml, uv.lock, .env.example
```

Dependencies (pinned): `fastapi`, `uvicorn`, `jinja2`, `psycopg[binary,pool]`, `pydantic-settings`,
`httpx`, `firebase-admin`, `cryptography`, `langfuse`; dev: `pytest`, `ruff`.
The OpenRouter call goes through plain `httpx` (one endpoint, no SDK needed).

### Screens and user flow

```
/login ──Google──► allowlisted? ──no──► "This app is private"
                       │yes
                       ▼
       onboarding_step != done ──► /onboarding
           1. Connect intervals.icu   (API key + athlete ID → test → "Connected as <name>") [skip]
           2. Your profile            (prefilled; missing required fields highlighted)    [skip]
           3. Goals, races and gear   (prefilled gear; add a race)                          [skip]
                       ▼
                    /today  ◄──────────────── default after onboarding
         ┌───────────────────────────────────────────┐
         │ Today · Sat 14 Nov                         │
         │ Profile 80% complete → finish (link)       │
         │ Next race: Lviv Half · 142 days · A        │
         │ ─────────── chat ───────────               │
         │ [What are my HR zones?] [Shoes mileage]    │
         │ [Message…                         ] (send) │
         └───────────────────────────────────────────┘
  /me        About me: profile · weight · gear · goals/races (view + edit, source badges)
  /settings  Connections (intervals.icu: connected, key ••••1a2b, test, disconnect),
             LLM usage this month ($ of $5), sign out
```

On a phone, the navigation is a bottom bar (Today · About me · Settings). On desktop it is a
left rail, and About me opens as a side panel next to the chat.

### Chat v1

- System prompt in one file (`app/prompts/chat_v1.md`). It contains the role, safety rules
  (no diagnosis; red flags → doctor) and "use only the profile below; say what is missing".
- Context: a compact JSON of the profile, active gear and upcoming goals (< 1.5k tokens) and the
  last 10 messages.
- Model: `google/gemini-3.1-flash-lite` via OpenRouter, `max_tokens` 800, timeout 30 s.
  The model id is checked against OpenRouter's model list before use.
- Before the call: budget check (sum of `llm_usage.cost_usd` this month < budget).
  After: store the message, usage and cost (from OpenRouter's usage response), Langfuse trace
  tagged with `user_id` and component `chat_v1`.

## Steps

0. **Accounts and tools** (you, following `docs/setup.md`)
   → verify: `gcloud config get project`, `firebase projects:list`, `psql "$DATABASE_URL" -c 'select 1'`.
1. **Scaffold:** uv project, FastAPI app with `/healthz`, config with startup validation, ruff,
   pytest, `.gitignore`, `.env.example`
   → verify: `uv run pytest` passes; `curl localhost:8000/healthz` → `ok`; app refuses to start
   without required env vars.
2. **DB + migrations:** `migrate.py`, `001_init.sql` on the Neon `dev` branch
   → verify: `uv run python -m app.migrate` applies once, a second run applies nothing; tables exist.
3. **Auth:** login page, `/auth/session`, `current_user`, logout, Origin check, private page for
   non-allowlisted emails
   → verify: tests for every route without a session (401/redirect), a non-allowlisted email
   (403, no row), a bad Origin (403); manual Google login on localhost.
4. **Design system + layout:** tokens, base layout (bottom bar / left rail), components (button,
   input, select, card, chip, toast, empty/loading/error states), light and dark
   → verify: screenshots at 375 px and 1280 px, light and dark, checked against
   `docs/design-guidelines.md` Part A2.
5. **intervals.icu connect:** settings form, test call, encrypt and store, disconnect; client with
   timeout, retry on 429/5xx, and error messages a user can act on
   → verify: tests with recorded responses (fixtures, secrets removed); a manual connect with
   my key shows my name; the key never appears in logs or HTML (grep the test output).
6. **About me:** profile, weight log, gear, goals/races; prefill from intervals.icu with source
   badges; edits write `audit_log`
   → verify: prefill matches the intervals.icu web UI for my account; edits persist; the
   isolation test covers all these endpoints.
7. **Onboarding v1:** the 3 steps, each skippable, resumable (`onboarding_step`)
   → verify: a fresh user finishes onboarding on a phone in < 2 min; skipping lands on /today
   with a "finish profile" prompt.
8. **Chat v1:** Today screen, chat endpoint, prompt file, budget, usage, Langfuse
   → verify: "what are my HR zones?" answers from the profile; with no zones it says they are
   missing; the trace is visible in Langfuse; a test with budget exceeded shows a friendly
   message and makes no LLM call.
9. **Deploy:** Dockerfile, secrets in Secret Manager, `gcloud run deploy`, `firebase.json`
   rewrite, `firebase deploy --only hosting`, prod migrations on the Neon `main` branch
   → verify: `https://<project-id>.web.app` → login works end to end; the `__session` cookie is set
   and accepted.
10. **Custom domain:** add `coach.lasiichuk.com` in Firebase Hosting, brother adds DNS records,
    add the domain to Firebase Auth authorized domains
    → verify: HTTPS with a valid certificate; login works from my phone on mobile data.
11. **Streaming probe:** a temporary `/debug/stream` endpoint; `curl -N` through the domain
    → verify: record whether chunks arrive incrementally; delete the endpoint; record the
    decision in this plan.
12. **Docs:** README (setup, run, deploy), report note for the deployment phase
    → verify: following the README in a clean clone gets the app running locally.

## Evaluation (M1)

| What | How | Pass |
|---|---|---|
| Every route is protected | `test_routes_protected.py` walks `app.routes` | 100% (except the allowed list) |
| User isolation | `test_isolation.py`: user B calls every endpoint with user A's ids | 0 leaks |
| Allowlist | test: a verified non-allowlisted email | 403, no DB row |
| Secrets | test: crypto round-trip; logs and HTML never contain the key | pass |
| intervals.icu client | fixture tests: success, 401, 429 retry, timeout | pass |
| Budget guard | test: over budget → no LLM call | pass |
| UI | screenshots 375/1280 × light/dark reviewed against guidelines | no A2 violations |
| End to end | manual: phone → login → onboarding → chat → sign out | works |

## Acceptance criteria

- [ ] `https://coach.lasiichuk.com` serves the app over HTTPS.
- [ ] Only the allowlisted emails can sign in; others see the private page.
- [ ] I can connect intervals.icu; profile, zones and gear are prefilled where intervals.icu has them.
- [ ] I can edit profile, weight, gear, goals and races; each edit is in `audit_log`.
- [ ] Chat answers using my profile and says when something is missing.
- [ ] LLM cost per user is recorded and the budget is enforced.
- [ ] All tests pass; the security tests exist and cover every endpoint.
- [ ] README lets someone run it locally.

## Main alternative considered

Hetzner VPS (€6/month) with Docker Compose (app + Postgres + Caddy): streaming works, no
cookie/timeout quirks, and the DNS is a single A record. It lost because it costs ~€6/month vs
~$0, and needs OS updates and backups. It stays the fallback if step 11 or the timeouts hurt.

## Open questions

See the questions in the chat; the answers update the Assumptions section above.
