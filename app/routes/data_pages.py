"""Nutrition, Health and Training pages (data views; the coach does the writing)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app import health, intervals, nutrition_stats, patterns, store
from app.auth import current_user
from app.db import connection
from app.web import shell, templates

router = APIRouter(dependencies=[Depends(current_user)])


def _today(user: store.User) -> date:
    return datetime.now(ZoneInfo(user.time_zone)).date()


@router.get("/nutrition", response_class=HTMLResponse)
def nutrition(request: Request, days: int = 1, user: store.User = Depends(current_user)):
    days = days if days in (1, 7, 30) else 1
    today = _today(user)
    first = today - timedelta(days=days - 1)
    meals = [lg for lg in store.logs_between(user.id, first, today)
             if lg["data"].get("nutrition") or lg["kind"] in ("meal", "drink", "alcohol")]
    by_day: dict = {}
    for m in reversed(meals):
        by_day.setdefault(m["day"], []).append(m)
    s = nutrition_stats.summary(user, today, days)
    top_days = max(days, 7)  # one day says nothing about what you eat most
    top = s["top_foods"] if days >= 7 else nutrition_stats.summary(user, today, 7)["top_foods"]
    return templates.TemplateResponse(request, "nutrition.html", shell(
        user, "/nutrition", days=days, rows=nutrition_stats.bars(user, today, days), s=s,
        by_day=by_day, top=top, top_days=top_days, today=today,
        totals=nutrition_stats.day_totals, water=nutrition_stats.water_l(
            store.logs_between(user.id, today, today))))


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


METRICS = [  # key, label, unit, what it means (shown on the card)
    ("hrv", "HRV", "ms", "Heart rate variability overnight. Higher than your usual = recovered; "
     "a drop of 10% or more = stress, illness, alcohol or hard training."),
    ("resting_hr", "Resting HR", "bpm", "Lower is better. 5+ bpm above your usual often means "
     "fatigue or getting ill."),
    ("sleep_h", "Sleep", "h", "Time asleep from your watch."),
    ("weight_kg", "Weight", "kg", "From your scale or what you entered in Garmin."),
    ("fitness", "Fitness", "", "intervals.icu fitness (CTL): your training load over the last "
     "6 weeks. Rises slowly when you train consistently."),
    ("fatigue", "Fatigue", "", "intervals.icu fatigue (ATL): load of the last week. Fitness minus "
     "fatigue is your form."),
    ("vo2max", "VO2max", "", "Estimated by your watch from runs with heart rate."),
    ("steps", "Steps", "", "Daily steps."),
]


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return None


@router.get("/health", response_class=HTMLResponse)
def health_page(request: Request, days: int = 90, user: store.User = Depends(current_user)):
    days = days if days in (30, 90, 365) else 90
    today = _today(user)
    connected = store.get_secret(user.id, "intervals") is not None
    sync_error = None
    if connected and (health.last_synced(user.id) or date(2000, 1, 1)) < today:
        try:
            health.sync(user.id, today)
        except intervals.IntervalsError as e:
            sync_error = str(e)
    else:
        health.maybe_sync(user.id, datetime.now(ZoneInfo(user.time_zone)))
    rows = health.series(user.id, today - timedelta(days=days), today)
    profile = store.get_profile(user.id)
    goal_w = _num((profile.get("target_weight_kg") or {}).get("value"))
    metrics = []
    for key, label, unit, about in METRICS:
        vals = [r.get(key) for r in rows]
        if days > 90:  # a year of daily points is noise; draw the 7-day average
            vals = rolling(vals, 7)
        last, last_day = health.latest(rows, key)
        nums = [v for v in vals if isinstance(v, (int, float))]
        if not nums:
            continue
        lo, hi = min(nums), max(nums)
        m = {"key": key, "label": label, "unit": unit, "about": about, "last": last,
             "last_day": last_day, "avg": round(sum(nums) / len(nums), 1), "min": lo, "max": hi}
        if key == "weight_kg" and goal_w:
            lo, hi = min(lo, goal_w), max(hi, goal_w)
            m["goal"] = goal_w
            m["goal_y"] = round(44 - 3 - (goal_w - lo) / ((hi - lo) or 1) * 38, 1)
        m["path"] = spark(vals, lo=lo, hi=hi)
        metrics.append(m)
    items = [f for f in store.list_facts(user.id, status=None)
             if f["category"] in ("health", "injury", "medication", "lab")]
    with connection() as c:
        reminders = c.execute("select * from reminders where user_id = %s and active and "
                              "(until is null or until >= %s) order by id",
                              (user.id, today)).fetchall()
    zones = (profile.get("sport_settings") or {}).get("value") or {}
    pain = health.pain_trend(user.id, today, max(days, 30))
    for p in pain:
        p["path"] = spark([v for _, v in p["points"]], lo=0, hi=10)
    return templates.TemplateResponse(request, "health.html", shell(
        user, "/health", days=days, metrics=metrics, items=items, reminders=reminders, zones=zones,
        connected=connected, sync_error=sync_error, today=today, pain=pain, goal_w=goal_w,
        patterns=patterns.find(user.id, today), has_wellness=bool(rows)))


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
    if connected and (health.last_synced(user.id) or date(2000, 1, 1)) < today:
        try:
            health.sync(user.id, today)
        except intervals.IntervalsError:
            pass
    else:
        health.maybe_sync(user.id, datetime.now(ZoneInfo(user.time_zone)))
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
    races = [f for f in items if f["category"] in ("race", "goal")]
    for r in races:
        try:
            when = date.fromisoformat(str((r.get("details") or {}).get("date") or "")[:10])
            r["days_left"] = (when - today).days
        except ValueError:
            r["days_left"] = None
    month = health.activities(user.id, today - timedelta(days=28), today)
    load = {}
    for a in month:
        t = load.setdefault(a["type"] or "Other", {"n": 0, "km": 0.0, "min": 0})
        t["n"] += 1
        t["km"] = round(t["km"] + (a.get("km") or 0), 1)
        t["min"] += a.get("minutes") or 0
    return templates.TemplateResponse(request, "training.html", shell(
        user, "/training", days=days, start=start, today=today, gear=gear, races=races,
        load=load, km=health.gear_km(user.id, gear), plan_source=(store.get_profile(user.id).get(
            "plan_source") or {}).get("value"), prev=(start - timedelta(days=7)).isoformat(),
        next=(start + timedelta(days=7)).isoformat()))
