# Setup: accounts, payments, keys, domain

Do these once, in order. About 45 minutes. Never paste keys into chat or commit them: put them
in `.env` (git-ignored) and, for prod, in Secret Manager (commands below).

## What you pay

| Service | Pay | Expected cost |
|---|---|---|
| Google Cloud / Firebase (Blaze plan) | card on file, pay-as-you-go | $0/month (free tiers); budget alert at $5 |
| OpenRouter | prepaid credits $10 (+5.5% fee) | ≈ $10.80 once; lasts ~1–2 months for two users |
| Neon, Langfuse, intervals.icu API, GitHub | free | $0 |
| Domain | already paid by your brother | $0 |

## 1. Keep this project apart from your work Google Cloud

You already use gcloud and the Firebase CLI with your work account (`gcloud config list` shows
the work project). Three rules keep this project from ever touching it:

1. **Never run plain `gcloud` for this project. Use `./scripts/gc` from the repo root.**
   It sets `CLOUDSDK_CONFIG=~/.config/gcloud-daily-coach` (a separate folder with its own
   accounts, configs and credentials) and always adds `--project=daily-coach-af64d`. Your work
   setup in `~/.config/gcloud` is not read or changed. Deploy scripts will also check the
   project before deploying.
2. **Do not run `gcloud auth application-default login`.** It would overwrite the work
   credentials file. The app does not need it: login tokens are checked against Google's
   public keys, and Cloud Run gets its own credentials in production.
3. **Firebase CLI: add your personal account and pin it to this folder.** `.firebaserc` already
   pins the project `daily-coach-af64d`; deploy commands also pass `--project`.

All local tools are already installed (brew, uv, node, psql, gcloud, firebase). Run once, from the
repo root, signing in with your **personal** Google account each time:

```bash
./scripts/gc auth login
```

```bash
./scripts/gc config set run/region europe-west1
```

```bash
firebase login:add
```

```bash
firebase login:use YOUR_PERSONAL_EMAIL
```

Check (both must show your personal account and `daily-coach-af64d`):

```bash
./scripts/gc config list
```

```bash
firebase login:list && firebase projects:list
```

In the browser, use a separate Chrome profile for your personal Google account. Then the
Firebase and Cloud consoles never open under the work account by mistake.

## 2. Firebase + Google Cloud project (project ID `daily-coach-af64d`)

The Firebase project *is* a Google Cloud project with the same ID. If you can't see it in Cloud
Console, the console is open under your work account: switch accounts (avatar, top right) or
use the personal Chrome profile.

1. **Check the project:** https://console.cloud.google.com/home/dashboard?project=daily-coach-af64d
   should show "daily-coach". "You need permissions" means you're on the wrong account.
2. **Billing (Blaze):** https://console.firebase.google.com/project/daily-coach-af64d/usage/details
   → **Modify plan** → **Blaze** → pick or create a billing account with your card. Cloud Run
   needs billing even when usage stays free. Budget alert (already done):
   https://console.cloud.google.com/billing/budgets
3. **Turn on Google sign-in:**
   https://console.firebase.google.com/project/daily-coach-af64d/authentication
   1. Click **Get started**.
   2. Open the **Sign-in method** tab, then **Add new provider** → **Google**.
   3. Toggle **Enable**. Public-facing name: `Daily Coach`. Support email: your personal email.
      Click **Save**.
   4. Open the **Settings** tab → **Authorized domains**. `localhost`,
      `daily-coach-af64d.firebaseapp.com` and `daily-coach-af64d.web.app` are there already. Add
      the custom domain only once your brother confirms it.
4. **Web app config:**
   https://console.firebase.google.com/project/daily-coach-af64d/settings/general
   1. Scroll to **Your apps** → click the **`</>`** (Web) icon.
   2. Nickname `coach-web`. Leave **Also set up Firebase Hosting** unticked. Click
      **Register app**.
   3. From the `firebaseConfig` snippet, copy `apiKey`, `authDomain` and `appId` into `.env`
      (section 7). These are public values (they ship in the page), not secrets.
5. **Enable the APIs** (repo root):

```bash
./scripts/gc services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

## 3. Neon (Postgres)

Project `daily-coach` (`summer-pond-25562927`), linked with the Neon CLI (`neon init`; the
folder link is in the git-ignored `.neon`). Branches:

| Branch | Use |
|---|---|
| `production` (default) | the live app; its URL goes only into Secret Manager |
| `main` | local development (child of `production`); pinned in `.neon`, so `neon env pull` writes its URLs into `.env` |

The app uses the pooled URL (`DATABASE_URL`, host contains `-pooler`); migrations use the direct
URL (`DATABASE_URL_UNPOOLED`). The Neon CLI is installed for Node 24; in a new terminal run
`nvm use 24` first. Check the connection with `uv run python -m app.db`.

## 4. OpenRouter (LLM)

1. https://openrouter.ai → sign in → **Credits** → add $10.
2. **Keys** → Create key `coach-dev` with credit limit $3, and `coach-prod` with limit $10.
   The limits are hard caps.
3. Dev key → `.env`; prod key → Secret Manager.

## 5. Langfuse (tracing)

1. https://cloud.langfuse.com (EU region) → sign up → create organization → project `daily-coach`.
2. Project settings → **API keys** → Create → copy the public key, secret key and host.

## 6. intervals.icu (each user does this for themselves)

1. https://intervals.icu → Settings → **Developer Settings** → generate an API key.
   Your athlete ID is shown there too (looks like `i123456`).
2. Settings → Connections → Garmin: check that it is connected and that uploading planned
   workouts is enabled (needed from milestone 4).
3. You enter the key in the app (Settings → Connections). For local scripts only, you can also put
   your own key in `.env`.

## 7. Secrets

There are two places, and nothing else holds a key:

- **Dev:** `.env` in the repo folder (git-ignored, only on your Mac). It has the dev values:
  the Neon `main` branch, OpenRouter `coach-dev`, the first Langfuse key pair, and a dev
  encryption key. `.env.example` lists the names.
- **Prod:** **Google Secret Manager**, in project `daily-coach-af64d`. This is a Google Cloud
  service, not something stored on the Mac: you send each value once from the terminal, and
  Cloud Run reads it at start-up. Nothing about it is saved locally.

**Prod values to store.** `.env.prod` (git-ignored, temporary) holds the four values, already
separated from dev: the Neon `production` URL, OpenRouter `coach-prod`, a fresh prod encryption
key, and the second Langfuse secret key. Store each one (repo root; the script asks for the value
with hidden input, so it never shows on screen or lands in shell history):

```bash
./scripts/set-secret database-url
```

```bash
./scripts/set-secret openrouter-api-key
```

```bash
./scripts/set-secret app-encryption-key
```

```bash
./scripts/set-secret langfuse-secret-key
```

For each one, open `.env.prod`, copy the value after `=`, paste it at the prompt, and press
Enter. The script prints the stored length. Then check that all four exist (this prints names
only, no values):

```bash
./scripts/gc secrets list
```

Then delete the temporary files that still hold prod values:

```bash
rm .env.prod .env.backup
```

Not secret, so set directly on Cloud Run at deploy: `ENV=prod`, `APP_ORIGIN`, `ALLOWED_EMAILS`,
`LANGFUSE_PUBLIC_KEY` (prod pair), `LANGFUSE_BASE_URL`, `LANGFUSE_TRACING_ENVIRONMENT=production`,
`FIREBASE_*`.

**Rotating a key later:** run the same `./scripts/set-secret NAME` with the new value; it adds a
new version, and the next deploy picks it up.

## 8. Domain: message to your brother

Firebase decides the exact records only after you add the domain (Firebase console → Hosting →
Add custom domain → `coach.lasiichuk.com`). Send this message first; send the records once
Firebase shows them. He does not need access to Firebase: only DNS changes are needed, so
adding him as a Firebase admin would give more access than required.

> Привіт! Хочу запустити свій застосунок (AI-асистент для тренувань) на піддомені
> **coach.lasiichuk.com**. Основний домен, сайт і пошта не зачіпаються — тільки новий піддомен.
>
> Що треба від тебе:
> 0. Чи ок тобі піддомен `coach.lasiichuk.com`, чи краще інший (напр. `train.`)?
> 1. Де керуються DNS-записи lasiichuk.com? (назва сервісу: реєстратор, Cloudflare, хостинг)
> 2. Чи вже є якісь записи для `coach.lasiichuk.com`? Якщо так — напиши які, щоб не було конфлікту.
> 3. Чи є на домені CAA-записи? Якщо є — треба дозволити `letsencrypt.org` і `pki.goog`
>    (через них видається SSL-сертифікат).
> 4. Коли я скину записи від Firebase (1 TXT для підтвердження + A-запис(и) для
>    `coach.lasiichuk.com`), додай їх, будь ласка. Якщо DNS на Cloudflare — для цих записів
>    вимкни проксі (сіра хмарка, "DNS only"), інакше сертифікат не видасться.
>    Або, якщо тобі зручніше, дай мені доступ лише до DNS-зони, і я додам сам.
>
> І ще: хочеш теж користуватися? Скинь свою Gmail-адресу — додам у список доступу. Потрібен буде
> твій API-ключ з intervals.icu (Settings → Developer Settings), його вводиш сам у застосунку,
> він зберігається зашифрованим. За все (AI, сервер) плачу я.

### 8b. When Ivan is ready: get the exact records

1. Open https://console.firebase.google.com/project/daily-coach-af64d/hosting/sites/daily-coach-af64d
   → **Add custom domain** → type the subdomain (e.g. `coach.lasiichuk.com`) → leave "redirect"
   off → **Continue**.
2. Done on 2026-11-14 through the Hosting API for `coach.lasiichuk.com` (DNS at GoDaddy,
   `ns19/ns20.domaincontrol.com`). Ivan added:
   - **CNAME** `coach` → `daily-coach-af64d.web.app`
   - **TXT** `_acme-challenge.coach` (a certificate check; Firebase can also validate over HTTP
     through the CNAME)

   No A record is needed. A name with a CNAME cannot also have an A record.
3. After he adds them, the console shows "Connected"; the certificate can take up to 24 h (usually
   less than 1 h).
4. Add the domain to sign-in: https://console.firebase.google.com/project/daily-coach-af64d/authentication/settings
   → Authorized domains → **Add domain**.
5. Let the app accept it, then redeploy:

```bash
EXTRA_ORIGIN=https://coach.lasiichuk.com ./scripts/deploy
```

## 9. GitHub

Create a private repo (e.g. `daily-coach`). Whether it becomes public for the course
submission is an open question: if public, the repo holds only demo-athlete data, which is the
plan anyway.

## Done when

- [ ] `./scripts/gc config list` shows your personal account and `daily-coach-af64d`.
- [ ] `firebase login:list` (run in the repo) uses your personal account; `firebase projects:list` shows the project.
- [ ] `psql "<neon dev url>" -c 'select 1'` works.
- [ ] `./scripts/gc secrets list` shows the 4 prod secrets; `.env.prod` and `.env.backup` are deleted.
- [ ] The message to your brother is sent.

Then tell me "setup done" plus the project ID, and nothing else.
