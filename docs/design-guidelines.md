# Design and engineering guidelines

Rules that keep this app from looking and behaving like a typical AI-generated app.
Read before any UI, architecture, auth or data work. Researched 2026-11-14 (sources at the end).

## Part A. Known AI failure modes and our rule for each

### A1. Architecture and security

Studies of AI-built ("vibe-coded") apps in 2026 report most apps shipping with at least one
vulnerability, concentrated in **broken access control, authentication failures, injection and
exposed secrets**. A second finding: coding agents do not reliably carry security context
forward, so protections added early go missing in code added later.

| # | Typical AI mistake | Our rule |
|---|---|---|
| S1 | Auth checked only in the browser, or only on some routes | Every route except `/login`, `/healthz` and static files requires a session. The default is deny: one FastAPI dependency `current_user` used by every router. A test lists all routes and fails if one is unprotected. Exception (plan 11 B4): `/hooks/mono/{token}`, the Monobank webhook: a random 32-byte token in the path (stored as a SHA-256 hash), accepts only items for that user's own accounts, writes one row, no LLM. |
| S2 | Queries not scoped to the user (user A reads user B's data) | Every table with personal data has `user_id`. Every data function takes `user_id` as its first argument; there is no "get by id" without it. A test with two users checks isolation for every endpoint. |
| S3 | Secrets in code, client JS, logs or git | Server-side only. Local: `.env` (git-ignored). Prod: Secret Manager. Users' third-party keys (intervals.icu) are encrypted at rest, never logged, never returned to the browser (only the last 4 characters), and never put in an LLM prompt. |
| S4 | LLM output trusted as-is | Every LLM output that drives logic is parsed into a Pydantic model. Invalid output → one retry → a clear error. Workouts pass a code validator before anything is written. |
| S5 | Prompt injection through imported data (ChatGPT export, activity notes, wiki pages) | Imported text is data. The LLM has no tool that writes outside the app without the user pressing **Send to watch**. The LLM never sees secrets. |
| S6 | Cookie sessions without CSRF protection | `__session` cookie: `HttpOnly`, `Secure`, `SameSite=Lax`. State-changing requests are POST only and must pass an `Origin` header check. |
| S7 | Unbounded cost (agent loops, huge prompts) | Max tool iterations per request, max tokens per call, a timeout per call, and a monthly budget per user, checked before each LLM call. |
| S8 | Schema changed by hand or by `create_all()` | Numbered SQL migrations in `migrations/`, applied by a small runner, recorded in `schema_migrations`. |
| S9 | Hallucinated APIs, packages or fields | Before using an external API field, check it against the official docs or a real response saved as a fixture. Pin dependency versions in `uv.lock`. |
| S10 | Over-engineering (microservices, queues, repository patterns for 5 tables) | One FastAPI app, one Postgres. Add a component only when a current requirement needs it. |
| S11 | Time handled in server local time | Store UTC (`timestamptz`). Each user has an IANA time zone in their profile. "Today" and "вчора" are resolved in the user's time zone. |
| S12 | Silent failures (`except: pass`, empty fallbacks) | Errors are logged with a request id and shown to the user in plain words with a next step. No silent default values. |
| S13 | The same logic duplicated in several places, drifting apart | One module per concern (`auth`, `db`, `intervals`, `llm`, `crypto`). Search before adding a new helper. |

### A2. UI / UX

| # | Typical AI mistake | Our rule |
|---|---|---|
| U1 | Generic look: Inter/Roboto, purple-indigo gradients, centered hero, rows of three identical cards, shadows on everything, emoji as icons | Use the design system in Part B. Gradients, emoji icons, decorative shadows and stock hero sections are banned. |
| U2 | Blank chat box: the user doesn't know what the assistant can do | The home screen shows today's state (day type, planned workout, last logs) and 3–4 suggestion chips based on context. The chat is part of the screen, not the whole screen. |
| U3 | Walls of text | Short answers. Plans and changes are shown as structured cards (before → after), not paragraphs. Long explanations are behind "Why?". |
| U4 | AI acts without asking | Anything written outside the app (intervals.icu, Garmin) shows a preview and needs **Send to watch**. Every applied change can be undone. |
| U5 | Opaque reasoning | Each recommendation shows its evidence as chips, e.g. "Sleep 5 h · HRV −12% vs 7-day · 4 beers · Knee: active". Each chip links to the source (wiki page, log entry, metric). |
| U6 | Long onboarding forms, everything asked up front | Onboarding is progressive. Prefill from intervals.icu first, ask only what is missing, every step can be skipped and finished later. |
| U7 | The user cannot correct the AI's memory | The Memory page (profile, items, files) is always visible and editable. AI edits are marked as AI and can be reverted. |
| U8 | Desktop-first layout that breaks on a phone | Mobile-first: input at the bottom within thumb reach, safe-area insets, 44 px touch targets, no horizontal scroll. Desktop adds a side panel; it is not a different app. |
| U9 | Missing loading, empty and error states | Every async view has all four states designed: loading, empty, error, success. |
| U10 | Placeholder or AI-sounding copy ("Unlock your potential!") | Plain, specific copy. Numbers with units. No exclamation marks, no marketing tone. |
| U11 | Fixing "generic" by adding more decoration | Fewer, deliberate choices: one accent color, one type family plus mono, a consistent spacing scale. |
| U12 | Checking a checklist instead of looking at the render | After UI work, look at real screenshots at phone width (375 px) and desktop width (1280 px), light and dark, before calling it done. |

## Part B. Design system v2: "training log" (2026-11-14)

v1 (cards, big status tiles, pills, two columns) hit 7 common AI-UI tells (Part A2 and
`docs/plans/04-redesign-onboarding-sources.md`). v2 replaces it.

**Concept:** a paper training diary set like a good watch face. Data is set plainly; the page
is one column you read from top to bottom.

- **Type:** **Fixel Text** (MacPaw, Ukrainian, OFL licence), self-hosted, weights 400/500 only.
  - Sizes: 15 px body, 13 px meta, 24 px page titles, 28 px day headline.
  - No tabular figures: Fixel's tabular zero is slashed.
- **Colour:**
  - Paper `#F3F2EF` / ink `#151515`; dark mode `#121212` / `#ECEBE7`.
  - **One accent**, signal orange `#E8562A`, used only for **Send to watch** and the recording
    mic.
  - Day types are a coloured *word* plus a 3 px tick (recover slate, easy green, normal ink,
    push orange). Never a filled block, and the colour always comes with the word.
- **Structure:**
  - No cards, no shadows, no pills, no gradients.
  - Sections are separated by 1 px rules and space. Lists are "log tables": a narrow left
    column (time) plus hairline rows.
  - 4 px radius on controls.
- **Hierarchy:** one primary action per screen (Send to watch, or Continue in setup). Everything
  secondary is an underlined text button.
- **Conversation:** a transcript (who · time, then text), not bubbles.
- **Layout:** one centred column, max 600 px, on phone and desktop. A pinned composer on Today
  (text, mic, send). Top navigation in text: Today · History · You · Settings.
- **Setup:** 4 steps with "N of 4", Skip, Back and Continue.
  - Step 1 connects intervals.icu.
  - Step 2 collects goal, race, sports and days.
  - Step 3 adds files and the user confirms the found facts.
  - Step 4 asks only for what's still missing.
- **Copy:** plain, with numbers and units. No exclamation marks; sentence case.
- **Motion:** none except state changes. `prefers-reduced-motion` is respected.

## Sources

- Vibe-coded app security audit (arXiv): https://arxiv.org/html/2606.23130v4
- SecurityWeek, vulnerabilities in vibe-coded apps: https://www.securityweek.com/vibe-coded-apps-riddled-with-exploitable-security-flaws/
- CSA research note on AI-generated code: https://labs.cloudsecurityalliance.org/research/csa-research-note-ai-generated-code-vulnerability-surge-2026/
- Anthropic cookbook, prompting for frontend aesthetics: https://platform.claude.com/cookbook/coding-prompting-for-frontend-aesthetics
- AI design slop patterns: https://www.developersdigest.tech/blog/ai-design-slop-and-how-to-spot-it
- Design system approach against slop: https://www.mindstudio.ai/blog/claude-design-avoid-ai-slop-design-system
- Chat UX, onboarding: https://getstream.io/blog/chat-ux/
- Conversational UI principles (UXmatters 2026): https://www.uxmatters.com/mt/archives/2026/02/conversational-user-interfaces-7-practical-ux-principles-for-modern-ai-systems.php
- First-session trust in AI products: https://www.uxmatters.com/mt/archives/2026/07/first-session-trust-in-ai-products-why-code-editors-onboard-users-better-than-chatbots.php
- AI slop pattern catalog (pixelslop): https://cdn.jsdelivr.net/npm/pixelslop@0.3.8/dist/skill/resources/ai-slop-patterns.md
- 7 signs a UI has been vibe coded: https://www.thefountaininstitute.com/blog/signs-vibe-coded-ui
