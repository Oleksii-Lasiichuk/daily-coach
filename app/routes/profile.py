"""Settings: you (basics, language, time zone, city), all reminders, your plan, intervals.icu.
Advanced (folded): models, own OpenRouter key, this month's cost. Admin only: hosting limits,
consoles and the app key's credit."""

from datetime import date
from zoneinfo import available_timezones

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg.types.json import Jsonb

from app import crypto, i18n, intervals, llm, store, weather
from app.auth import current_user
from app.config import get_settings
from app.db import connection
from app.web import is_admin, shell, templates, ui

router = APIRouter(dependencies=[Depends(current_user)])
NUDGES = [("morning", "Morning plan"), ("breakfast", "Log breakfast"), ("lunch", "Log lunch"),
          ("dinner", "Log dinner"), ("evening", "Evening check-in")]
# Free-tier limits checked 2026-11-14 (Neon plans page, Langfuse pricing, Google Cloud pricing).
LIMITS = [
    ("OpenRouter (AI models)", "Prepaid credit with a hard limit per key", "live below"),
    ("Neon Postgres (Free)", "1 GB storage per project · 100 CU-hours compute and 5 GB network "
     "transfer per month", "https://console.neon.tech"),
    ("Langfuse Cloud (Hobby)", "50,000 units per month · 30 days of history · 2 users",
     "https://cloud.langfuse.com"),
    ("Google Cloud Run", "Free each month: 2 million requests, 180,000 vCPU-seconds, 360,000 "
     "GiB-seconds", "https://console.cloud.google.com/run?project=daily-coach-af64d"),
    ("Firebase Hosting + Auth", "Free hosting quota (10 GB storage, 360 MB/day transfer); Google "
     "sign-in is free", "https://console.firebase.google.com/project/daily-coach-af64d/usage"),
    ("Cloud Scheduler", "3 jobs free per billing account (we use 1)",
     "https://console.cloud.google.com/cloudscheduler?project=daily-coach-af64d"),
]


def prefs(user_id: str) -> dict:
    with connection() as c:
        c.execute("insert into user_prefs (user_id) values (%s) on conflict do nothing", (user_id,))
        return c.execute("select * from user_prefs where user_id = %s", (user_id,)).fetchone()


def openrouter_credit() -> dict | None:
    try:
        r = httpx.get("https://openrouter.ai/api/v1/key", timeout=8, headers={
            "Authorization": f"Bearer {get_settings().openrouter_api_key}"})
        return r.json().get("data") if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


ZONES = sorted(z for z in available_timezones()
               if "/" in z and not z.startswith(("Etc/", "SystemV/")))
PLAN_SOURCES = [("garmin_coach", "Garmin Coach"),
                ("intervals", "A plan in my intervals.icu calendar"),
                ("coach", "A human coach"), ("none", "No plan: the coach plans for me")]


@router.get("/profile")
def old_profile():
    return RedirectResponse("/settings", status_code=301)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: store.User = Depends(current_user)):
    admin = is_admin(user)
    with connection() as c:
        subs = c.execute("select count(*) as n from push_subscriptions where user_id = %s",
                         (user.id,)).fetchone()["n"]
        reminders = c.execute("select * from reminders where user_id = %s and active and "
                              "(until is null or until >= current_date) order by id",
                              (user.id,)).fetchall()
        db_mb = c.execute("select pg_database_size(current_database()) / 1048576.0 as mb"
                          ).fetchone()["mb"] if admin else 0
    profile_vals = {k: v["value"] for k, v in store.get_profile(user.id).items()}
    return templates.TemplateResponse(request, "settings.html", shell(
        user, "/settings", p=prefs(user.id), models=llm.MODELS, nudges=NUDGES,
        limits=LIMITS if admin else [], credit=openrouter_credit() if admin else None,
        db_mb=round(float(db_mb), 1), month_cost=store.month_cost(user.id),
        cap=llm.MONTHLY_CAP_USD, own_key=store.get_secret(user.id, "openrouter"), subs=subs,
        prof=profile_vals, reminders=reminders, zones=ZONES, langs=i18n.LANGS,
        plan_sources=PLAN_SOURCES, secret=store.get_secret(user.id, "intervals"),
        summary=intervals.athlete_summary(profile_vals), saved=request.query_params.get("saved"),
        error=request.query_params.get("error"), vapid=get_settings().vapid_public_key))


@router.post("/settings/lang")
def set_lang(lang: str = Form("en"), next: str = Form("/settings"),
             user: store.User = Depends(current_user)):
    if lang in i18n.LANGS:
        prefs(user.id)
        with connection() as c:
            c.execute("update user_prefs set lang = %s where user_id = %s", (lang, user.id))
    ok = next.startswith("/") and not next.startswith("//")
    return RedirectResponse(next if ok else "/settings", status_code=303)


@router.post("/settings/place")
def set_place(time_zone: str = Form(""), city: str = Form(""), plan_source: str = Form(""),
              user: store.User = Depends(current_user)):
    if time_zone in ZONES or time_zone == "UTC":
        store.set_time_zone(user.id, time_zone)
    if plan_source in dict(PLAN_SOURCES):
        store.set_profile_field(user.id, "plan_source", plan_source, "user", actor="user")
    city = city.strip()
    current = (store.get_profile(user.id).get("location") or {}).get("value") or {}
    if city and city != current.get("name"):
        place = weather.geocode(city)
        if not place:
            return RedirectResponse("/settings?error=city#you", status_code=303)
        store.set_profile_field(user.id, "location", place, "user", actor="user")
    elif not city and current:
        store.delete_profile_field(user.id, "location")
    return RedirectResponse("/settings?saved=you#you", status_code=303)


@router.post("/settings/report-now")
def report_now(user: store.User = Depends(current_user)):
    """Writes this morning's report now (into the chat, and as a push if it's on)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import push
    text = push.morning_report(user.id, datetime.now(ZoneInfo(user.time_zone)))
    if text:
        push.send(user.id, "Morning report", text[:240])
    return RedirectResponse("/" if text else "/settings?error=report#reminders", status_code=303)


@router.post("/settings/reminders")
def add_reminder(text: str = Form(""), times: str = Form(""), until: str = Form(""),
                 user: store.User = Depends(current_user)):
    clean = sorted({t.strip()[:5] for t in times.replace(";", ",").split(",")
                    if len(t.strip()) >= 4 and ":" in t})
    try:
        end = date.fromisoformat(until) if until else None
    except ValueError:
        end = None
    if text.strip() and clean:
        with connection() as c:
            c.execute("insert into reminders (user_id, kind, text, times, until) values "
                      "(%s, 'custom', %s, %s, %s)", (user.id, text.strip()[:200], clean, end))
    return RedirectResponse("/settings#reminders", status_code=303)


@router.post("/profile/models")
def save_models(model_default: str = Form(...), model_deep: str = Form(...),
                user: store.User = Depends(current_user)):
    if model_default in llm.MODELS and model_deep in llm.MODELS:
        prefs(user.id)
        with connection() as c:
            c.execute("update user_prefs set model_default = %s, model_deep = %s, updated_at = "
                      "now() where user_id = %s", (model_default, model_deep, user.id))
    return RedirectResponse("/settings#advanced", status_code=303)


@router.post("/profile/key")
def save_key(api_key: str = Form(""), user: store.User = Depends(current_user)):
    key = api_key.strip()
    if key.startswith("sk-or-"):
        store.save_secret(user.id, "openrouter", crypto.encrypt(key), crypto.last4(key), None)
    elif not key:
        store.delete_secret(user.id, "openrouter")
    return RedirectResponse("/settings#advanced", status_code=303)


@router.post("/profile/nudges")
async def save_nudges(request: Request, user: store.User = Depends(current_user)):
    form = await request.form()
    times = {k: str(form.get(k, ""))[:5] for k, _ in NUDGES if str(form.get(k, "")).count(":") == 1}
    on = form.get("enabled") == "1"
    prefs(user.id)
    with connection() as c:
        c.execute("update user_prefs set nudges = %s, nudges_on = %s, updated_at = now() "
                  "where user_id = %s", (Jsonb(times), on, user.id))
    return RedirectResponse("/settings#reminders", status_code=303)


@router.post("/profile/basics")
async def save_basics(request: Request, user: store.User = Depends(current_user)):
    form = await request.form()
    for key in ("weight_kg", "height_cm", "birth_year", "sleep_target_h", "target_weight_kg"):
        val = str(form.get(key, "")).strip()[:60]
        if val:
            store.set_profile_field(user.id, key, val, "user", actor="user")
    nxt = str(form.get("next", ""))
    ok = nxt.startswith("/") and not nxt.startswith("//")
    return RedirectResponse(nxt if ok else "/settings?saved=you#you", status_code=303)


def intervals_context(user: store.User, **extra) -> dict:
    profile_vals = {k: v["value"] for k, v in store.get_profile(user.id).items()}
    return {**ui(user), "secret": store.get_secret(user.id, "intervals"),
            "summary": intervals.athlete_summary(profile_vals), **extra}


@router.post("/intervals/connect", response_class=HTMLResponse)
def connect(request: Request, api_key: str = Form(""), athlete_id: str = Form(""),
            user: store.User = Depends(current_user)):
    try:
        athlete = intervals.connect_user(user.id, api_key, athlete_id)
        ctx = intervals_context(user, connected_name=athlete.get("name") or athlete_id.strip())
    except intervals.IntervalsError as e:
        ctx = intervals_context(user, error=str(e), athlete_id=athlete_id)
    return templates.TemplateResponse(request, "partials/intervals.html", ctx,
                                      headers={"HX-Trigger": "intervalsChanged"})


@router.post("/intervals/disconnect", response_class=HTMLResponse)
def disconnect(request: Request, user: store.User = Depends(current_user)):
    store.delete_secret(user.id, "intervals")
    return templates.TemplateResponse(request, "partials/intervals.html", intervals_context(user))
