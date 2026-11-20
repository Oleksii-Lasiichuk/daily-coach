"""Nutrition, Health and Training pages (data views; the coach does the writing)."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app import health, intervals, llm, nutrition_stats, patterns, store
from app.auth import current_user
from app.db import connection
from app.pipeline import day_review
from app.web import shell, templates

router = APIRouter(dependencies=[Depends(current_user)])


def _today(user: store.User) -> date:
    return datetime.now(ZoneInfo(user.time_zone)).date()


@router.get("/nutrition", response_class=HTMLResponse)
def nutrition(request: Request, days: int = 0, day: str = "",
              user: store.User = Depends(current_user)):
    """One day, Garmin-style, with ‹ date › (default), or the 7/30-day trends (?days=)."""
    today = _today(user)
    if days in (7, 30):
        return _nutrition_trends(request, user, today, days)
    try:
        d = min(date.fromisoformat(day), today) if day else today
    except ValueError:
        d = today
    v = nutrition_stats.day_view(user, d, today)
    return templates.TemplateResponse(request, "nutrition_day.html", shell(
        user, "/nutrition", v=v, today=today, prev=d - timedelta(days=1),
        next=d + timedelta(days=1) if d < today else None))


@router.get("/nutrition/review", response_class=HTMLResponse)
def nutrition_review(request: Request, day: str = "", user: store.User = Depends(current_user)):
    """C9: the coach's review of one day (loaded after the page; cached per day)."""
    today = _today(user)
    try:
        d = min(date.fromisoformat(day), today)
    except ValueError:
        return HTMLResponse("", status_code=404)
    v = nutrition_stats.day_view(user, d, today)
    rv, error = None, None
    if v["logs"]:
        try:
            rv = day_review.cached_review(user.id, v["review_input"])
        except llm.BudgetExceeded as e:
            error = str(e)
        except llm.LLMError:
            error = "Couldn't write the review. Try again later."
    return templates.TemplateResponse(request, "partials/day_review.html",
                                      shell(user, "/nutrition", rv=rv, error=error))


def _nutrition_trends(request: Request, user: store.User, today: date, days: int):
    first = today - timedelta(days=days - 1)
    meals = [lg for lg in store.logs_between(user.id, first, today)
             if lg["data"].get("nutrition") or lg["kind"] in ("meal", "drink", "alcohol")]
    by_day: dict = {}
    for m in reversed(meals):
        by_day.setdefault(m["day"], []).append(m)
    s = nutrition_stats.summary(user, today, days)
    top = s["top_foods"]
    return templates.TemplateResponse(request, "nutrition.html", shell(
        user, "/nutrition", days=days, rows=nutrition_stats.bars(user, today, days), s=s,
        by_day=by_day, top=top, top_days=days, today=today,
        totals=nutrition_stats.day_totals, water=0))


def rolling(values: list, n: int) -> list:
    out = []
    for i in range(len(values)):
        win = [v for v in values[max(0, i - n + 1):i + 1] if isinstance(v, (int, float))]
        out.append(sum(win) / len(win) if win else None)
    return out


def spark(values: list[float | None], w: int = 200, h: int = 44,
          lo: float | None = None, hi: float | None = None) -> str:
    """SVG path for a sparkline (None values skipped). lo/hi fix the scale."""
    pts = [(i, v) for i, v in enumerate(values) if isinstance(v, (int, float))]
    if len(pts) < 2:
        return ""
    lo = min(v for _, v in pts) if lo is None else lo
    hi = max(v for _, v in pts) if hi is None else hi
    span = (hi - lo) or 1
    n = max(1, len(values) - 1)
    coords = [(round(i * w / n, 1), round(h - 3 - (v - lo) / span * (h - 6), 1)) for i, v in pts]
    return "M" + " L".join(f"{x},{y}" for x, y in coords)


# key, label, unit, decimals, what it means. Only metrics with data are offered.
METRICS = [
    ("hrv", "HRV", "ms", 0, "Heart rate variability overnight. Higher than your usual = "
     "recovered; a drop of 10% or more = stress, illness, alcohol or hard training."),
    ("resting_hr", "Resting HR", "bpm", 0, "Lower is better. 5+ bpm above your usual often means "
     "fatigue or getting ill."),
    ("sleep_h", "Sleep", "h", 1, "Time asleep from your watch."),
    ("sleep_score", "Sleep score", "", 0, "Garmin's 0–100 sleep score."),
    ("sleep_quality", "Sleep quality", "", 0, "intervals.icu sleep quality (1 great … 4 poor)."),
    ("sleep_hr", "Sleeping HR", "bpm", 0, "Average heart rate while asleep."),
    ("stress", "Stress", "", 0, "Average stress for the day, as sent by your watch."),
    ("readiness", "Readiness", "", 0, "Training readiness, as sent by your watch."),
    ("spo2", "SpO2", "%", 0, "Blood oxygen overnight."),
    ("respiration", "Respiration", "brpm", 1, "Breaths per minute while asleep."),
    ("weight_kg", "Weight", "kg", 1, "From your scale or what you entered in Garmin."),
    ("body_fat", "Body fat", "%", 1, "From a smart scale."),
    ("vo2max", "VO2max", "", 0, "Estimated by your watch from runs with heart rate."),
    ("fitness", "Fitness", "", 0, "intervals.icu fitness (CTL): training load of the last 6 "
     "weeks. Rises slowly when you train consistently."),
    ("fatigue", "Fatigue", "", 0, "intervals.icu fatigue (ATL): load of the last week."),
    ("form", "Form", "", 0, "Fitness minus fatigue. −10 to −30: building; below −30: too much; "
     "above +5: fresh."),
    ("load", "Training load", "", 0, "Sum of the day's session loads (intervals.icu)."),
    ("km", "Distance", "km", 1, "Total distance of the day's sessions."),
    ("steps", "Steps", "", 0, "Daily steps."),
]


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return None


def chart_data(user_id: str, today: date, days: int = 730) -> dict:
    """Every day of the last `days` (gaps as null) for the interactive charts."""
    first = today - timedelta(days=days - 1)
    rows = {r["day"]: r for r in health.series(user_id, first, today)}
    acts: dict[str, dict] = {}
    for a in health.activities(user_id, first, today):
        d = acts.setdefault(a["day"], {"load": 0, "km": 0})
        d["load"] += a.get("load") or 0
        d["km"] = round(d["km"] + (a.get("km") or 0), 1)
    dates = [(first + timedelta(days=i)).isoformat() for i in range(days)]
    start = next((i for i, d in enumerate(dates) if d in rows or d in acts), len(dates) - 1)
    dates = dates[start:]
    series, meta = {}, []
    for key, label, unit, dec, about in METRICS:
        src = acts if key in ("load", "km") else rows
        vals = [(src.get(d) or {}).get(key) for d in dates]
        vals = [v if isinstance(v, (int, float)) else None for v in vals]
        if key in ("load", "km"):
            vals = [v or None for v in vals]
        if sum(v is not None for v in vals) < 2:
            continue
        series[key] = vals
        meta.append({"key": key, "label": label, "unit": unit, "dec": dec, "about": about})
    return {"dates": dates, "series": series, "meta": meta}


def tiles(rows: list[dict], meta: list[dict], today: date) -> list[dict]:
    """Latest value, 7-day and 30-day averages per metric."""
    def avg(key: str, dec: int, n: int):
        v = [r[key] for r in rows if r["day"] > (today - timedelta(days=n)).isoformat()
             and isinstance(r.get(key), (int, float))]
        return round(sum(v) / len(v), dec or None) if v else None

    out = []
    for m in meta:
        if m["key"] in ("load", "km"):
            continue
        last, last_day = health.latest(rows, m["key"])
        if last is not None:
            out.append(m | {"last": last, "last_day": last_day, "avg7": avg(m["key"], m["dec"], 7),
                            "avg30": avg(m["key"], m["dec"], 30)})
    return out


@router.get("/health", response_class=HTMLResponse)
def health_page(request: Request, user: store.User = Depends(current_user)):
    today = _today(user)
    connected = store.get_secret(user.id, "intervals") is not None
    sync_error = None
    if connected and health.last_synced(user.id) is None:  # first visit after connecting
        try:
            health.sync(user.id, today)
        except intervals.IntervalsError as e:
            sync_error = str(e)
    else:
        health.sync_soon(user.id, datetime.now(ZoneInfo(user.time_zone)))
    profile = store.get_profile(user.id)
    data = chart_data(user.id, today)
    rows = health.series(user.id, today - timedelta(days=30), today)
    items = [f for f in store.list_facts(user.id, status=None)
             if f["category"] in ("health", "injury", "medication", "lab")]
    with connection() as c:
        reminders = c.execute("select * from reminders where user_id = %s and active and "
                              "(until is null or until >= %s) order by id",
                              (user.id, today)).fetchall()
    zones = (profile.get("sport_settings") or {}).get("value") or {}
    pain = health.pain_trend(user.id, today, 90)
    for p in pain:
        p["path"] = spark([v for _, v in p["points"]], lo=0, hi=10)
    return templates.TemplateResponse(request, "health.html", shell(
        user, "/health", data=data, tiles=tiles(rows, data["meta"], today), items=items,
        reminders=reminders, zones=zones, connected=connected, sync_error=sync_error,
        today=today, pain=pain, patterns=patterns.find(user.id, today),
        goal_w=_num((profile.get("target_weight_kg") or {}).get("value"))))


@router.get("/training", response_class=HTMLResponse)
def training(request: Request, week: str = "", user: store.User = Depends(current_user)):
    today = _today(user)
    try:
        start = date.fromisoformat(week) if week else today - timedelta(days=today.weekday())
    except ValueError:
        start = today - timedelta(days=today.weekday())
    start -= timedelta(days=start.weekday())
    end = start + timedelta(days=6)
    connected = store.get_secret(user.id, "intervals") is not None
    if connected and health.last_synced(user.id) is None:  # first visit after connecting
        try:
            health.sync(user.id, today)
        except intervals.IntervalsError:
            pass
    else:
        health.sync_soon(user.id, datetime.now(ZoneInfo(user.time_zone)))
    acts = health.activities(user.id, start, end)
    logs = store.logs_between(user.id, start, end)
    with connection() as c:
        props = c.execute("select * from proposals where user_id = %s and day between %s and %s "
                          "and status in ('proposed', 'applied') order by id", (user.id, start,
                                                                                  end)).fetchall()
        assessments = {a["day"]: a for a in c.execute(
            "select day, day_type from day_assessments where user_id = %s and day between %s "
            "and %s", (user.id, start, end)).fetchall()}
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        days.append({"date": d, "acts": [a for a in acts if a["day"] == d.isoformat()],
                     "planned": [lg for lg in logs if lg["day"] == d and lg["kind"] ==
                                 "planned_workout"],
                     "proposals": [p for p in props if p["day"] == d],
                     "type": (assessments.get(d) or {}).get("day_type")})
    items = store.list_facts(user.id, status=None)
    gear = [f for f in items if f["category"] == "gear"]
    goals_ctx = goal_cards(user.id, [f for f in items if f["category"] in ("race", "goal")],
                           today)
    month = health.activities(user.id, today - timedelta(days=28), today)
    load = {}
    for a in month:
        t = load.setdefault(a["type"] or "Other", {"n": 0, "km": 0.0, "min": 0})
        t["n"] += 1
        t["km"] = round(t["km"] + (a.get("km") or 0), 1)
        t["min"] += a.get("minutes") or 0
    weeks = []  # weekly km and hours for the last 8 weeks (bars)
    monday = today - timedelta(days=today.weekday())
    eight = health.activities(user.id, monday - timedelta(days=49), today)
    for i in range(7, -1, -1):
        w0 = monday - timedelta(days=7 * i)
        w1 = (w0 + timedelta(days=6)).isoformat()
        acts_w = [a for a in eight if w0.isoformat() <= str(a["day"]) <= w1]
        weeks.append({"start": w0, "km": round(sum(a.get("km") or 0 for a in acts_w)),
                      "hours": round(sum(a.get("minutes") or 0 for a in acts_w) / 60, 1)})
    return templates.TemplateResponse(request, "training.html", shell(
        user, "/training", days=days, weeks=weeks, start=start, today=today, gear=gear,
        this_week=today - timedelta(days=today.weekday()),
        gear_types={f["id"]: gear_type(f) for f in gear}, **goals_ctx,
        load=load, km=health.gear_km(user.id, gear), plan_source=(store.get_profile(user.id).get(
            "plan_source") or {}).get("value"), prev=(start - timedelta(days=7)).isoformat(),
        next=(start + timedelta(days=7)).isoformat()))


def _when(f: dict) -> date | None:
    raw = (f.get("details") or {}).get("date") or (str(f["until"]) if f.get("until") else "")
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def goal_cards(user_id: str, items: list[dict], today: date) -> dict:
    """Races (countdown, share of the build-up done, fitness trend) and goals (weight progress
    when it is a weight goal)."""
    rows = health.series(user_id, today - timedelta(days=400), today)
    fit_now, _ = health.latest(rows, "fitness")
    month_ago = [r for r in rows if r["day"] <= (today - timedelta(days=28)).isoformat()]
    fit_then, _ = health.latest(month_ago, "fitness")
    weight_now, _ = health.latest(rows, "weight_kg")
    target_w = _num((store.get_profile(user_id).get("target_weight_kg") or {}).get("value"))
    races, past, goals = [], [], []
    for f in items:
        if f["status"] != "active":
            continue
        d = f.get("details") or {}
        if f["category"] == "race":
            when = _when(f)
            if when and when < today:
                past.append(f | {"when": when})
                continue
            card = f | {"when": when, "days_left": (when - today).days if when else None,
                        "target": d.get("target_time") or d.get("target_pace"),
                        "distance": d.get("distance")}
            if when and (today - f["created_at"].date()).days >= 7:  # not on the day it's set
                total = max(1, (when - f["created_at"].date()).days)
                card["done_pct"] = max(0, min(100, round(100 * (today - f["created_at"].date())
                                                         .days / total)))
            races.append(card)
        else:
            card = dict(f)
            stated = re.search(r"(\d{2,3}(?:[.,]\d)?)\s*(?:kg|кг)", f["text"].lower())
            goal_w = _num(stated.group(1)) if stated else target_w
            if goal_w and weight_now and any(w in f["text"].lower() for w in (
                    "weight", "kg", "ваг", "схуд", "кг")):
                target_w = goal_w
                start_rows = [r for r in rows if r["day"] >= f["created_at"].date().isoformat()]
                start_w, _ = next(((r["weight_kg"], r["day"]) for r in start_rows
                                   if r.get("weight_kg")), (weight_now, None))
                span = (start_w - target_w) or 1
                card["weight"] = {"start": start_w, "now": weight_now, "target": target_w,
                                  "pct": max(0, min(100, round(100 * (start_w - weight_now)
                                                               / span)))}
            goals.append(card)
    races.sort(key=lambda r: r["when"] or date.max)
    return {"races": races, "past_races": past, "goals": goals,
            "fitness": {"now": fit_now, "then": fit_then}}


def gear_type(f: dict) -> str:
    t = ((f.get("details") or {}).get("type") or "").lower() + " " + f["text"].lower()
    for key, words in [("hrm", ("hrm", "strap", "heart rate", "пульсометр", "нагруд")),
                       ("watch", ("watch", "forerunner", "fenix", "годинник", "epix", "coros")),
                       ("bike", ("bike", "велосипед", "ride", "trek", "canyon")),
                       ("shoes", ("shoe", "кросів", "кросовк", "pegasus", "speedcross"))]:
        if any(w in t for w in words):
            return key
    return "other"
