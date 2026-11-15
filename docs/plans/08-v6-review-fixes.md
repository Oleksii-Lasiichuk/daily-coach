# Plan 08 — v6: fixes from the pre-submission review

CRISP-DM phases: 5. Evaluation, 6. Deployment (with small 4. Modeling fixes).

## Goal

An independent review of v5 (a second model walked every page on a seeded demo athlete and read
the report) found ten defects, stale report files, evaluation gaps and no way for a grader to
run the app. Fix them, make the app runnable locally without personal accounts, and publish.

## Scope

- In: the ten verified defects; Today, Training, Journal and Settings flow fixes; a demo
  athlete with fake intervals.icu (dev only) and Docker Postgres; an end-to-end agent eval,
  95% intervals, a majority baseline; the short report, the agentic-coding page, two skills;
  deploy.
- Out: manual mode without intervals.icu, vision eval, C3 food-database grounding, a native
  speaker's read of the Ukrainian strings.

## Steps

1. Defects: rest-day badge, `:disabled` style, plural, digest crash, setup on phones, mixed
   language (C5/C6 write in the UI language), sleep dating (C2 rule + 3 cases), patterns
   (Welch t), sex in setup and Settings → verify: tests, C2 eval, browser.
2. Flows: "Check my day" loading line, deltas on tiles, one-line dismissible notifications
   banner, 8-week bars on Training, build-up bar after a week, weight goal from the goal text,
   Journal chips instead of the raw digest, one Save in Settings, axis units on charts →
   verify: browser at 375 and 1280.
3. Demo mode: `app/demo.py`, `/demo-login` (404 unless dev + localhost), `docker-compose.yml`,
   optional Langfuse/Firebase settings → verify: `tests/test_demo.py`, a clean Postgres run.
4. Evals: `evals/run_e2e.py`, `evals/stats.py` → verify: results files.
5. Report: `docs/report/README.md`, `07-agentic-coding.md`, stale terms, contradictions.
6. Deploy → verify: `/status`, a page on the live site.

## Acceptance criteria

- [x] All ten defects fixed and covered by a test, an eval case or a browser check.
- [x] `docker compose up -d && uv run python -m app.demo seed` + `/demo-login` works on an empty
      database with only an OpenRouter key.
- [x] `/demo-login` is 404 in prod and behind a proxy (tests).
- [x] Every component has a metric or a stated reason why not.
- [x] Deployed (see Result).

## Result

- **Defects:** all ten fixed. Checked in the browser on the demo athlete (Today, Training,
  Journal, Settings at 375 and 1280 px), by tests (`test_v6.py`, `test_demo.py`, patterns) and
  by evals (C2 with 3 new cases: F1 0.915, all three pass).
- **Patterns:** Welch t ≥ 2.5 chosen by simulation: false patterns on random 90-day logs 6.5%
  (old rule about 40%); a real 10% HRV drop is found 43% of the time.
- **New eval:** end-to-end agent, 12 turns. First run 11/12 and it found a real bug (race dates
  missing from the coach's context); after the fix 12/12. Nothing reached the watch without a
  tap in any run.
- **Intervals:** `evals/stats.py`; e.g. C7 recall 1.00 has a lower bound of 0.84, injection
  0/10 an upper bound of 0.28. C5 majority-class baseline: accuracy 0.33, κ 0.
- **Clean copy:** tracked files only, empty Postgres, only an OpenRouter key → migrate, seed,
  demo login and a real chat turn worked.
- **Tests:** 46 pass; ruff clean.
- **Not verified:** a real phone with push; a real meal photo and a plan screenshot after the
  v6 changes; how the new Ukrainian strings read to a native speaker; the deployed site with
  Ivan's account.
