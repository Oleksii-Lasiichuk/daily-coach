"""Health data: a year of wellness and activities synced from intervals.icu into Postgres
(refreshed hourly), the planned sessions on the intervals.icu calendar, series for charts, the
pain trend, shoe km and a compact summary for the coach."""

import logging
from datetime import date, datetime, timedelta
from statistics import mean

from psycopg.types.json import Jsonb

from app import intervals, store
from app.db import connection

log = logging.getLogger("health")
RUN_TYPES = {"Run", "TrailRun", "VirtualRun", "Treadmill"}

# intervals.icu wellness field -> our key. Garmin fills a subset; empty ones are skipped.
FIELDS = {"hrv": "hrv", "restingHR": "resting_hr", "sleepSecs": "sleep_h", "sleepScore":
          "sleep_score", "sleepQuality": "sleep_quality", "avgSleepingHR": "sleep_hr",
          "weight": "weight_kg", "bodyFat": "body_fat", "vo2max": "vo2max", "ctl": "fitness",
          "atl": "fatigue", "rampRate": "ramp", "steps": "steps", "stress": "stress",
          "readiness": "readiness", "spO2": "spo2", "respiration": "respiration",
          "kcalConsumed": "kcal_in"}
VERSION = 2  # bump when FIELDS grow: the next sync re-reads the whole year


def last_synced(user_id: str) -> date | None:
    with connection() as c:
        r = c.execute("select max(day) as d from wellness_daily where user_id = %s",
                      (user_id,)).fetchone()
    return r["d"] if r else None


def sync(user_id: str, today: date, days: int = 365) -> int:
    """Fetches what's missing (from the last synced day − 3, or a year back). Returns rows."""
    conn = intervals.connection_for(user_id)
    last = last_synced(user_id)
    with connection() as c:
        current = c.execute("select exists (select 1 from wellness_daily where user_id = %s and "
                            "(data->>'v')::int = %s) as ok", (user_id, VERSION)).fetchone()["ok"]
    first = (last - timedelta(days=3)) if last and current else today - timedelta(days=days)
    wellness = intervals.get_wellness(conn, first, today)
    acts = intervals.get_activities(conn, first, today)
    with connection() as c:
        with c.cursor() as cur:
            cur.executemany(
                "insert into wellness_daily (user_id, day, data) values (%s, %s, %s) "
                "on conflict (user_id, day) do update set data = excluded.data",
                [(user_id, w["id"], Jsonb({"v": VERSION} | {
                    FIELDS[k]: w.get(k) for k in FIELDS if w.get(k) is not None}))
                 for w in wellness if w.get("id")])
            cur.executemany(
                "insert into activities (user_id, id, day, type, data) values (%s, %s, %s, %s, %s) "
                "on conflict (user_id, id) do update set data = excluded.data",
                [(user_id, str(a["id"]), (a.get("start_date_local") or "")[:10] or today,
                  a.get("type"), Jsonb({
                      "name": a.get("name"), "km": round((a.get("distance") or 0) / 1000, 1),
                      "minutes": round((a.get("moving_time") or 0) / 60),
                      "load": a.get("icu_training_load"), "avg_hr": a.get("average_heartrate"),
                      "feel": a.get("feel"), "rpe": a.get("icu_rpe"),
                      "max_hr": a.get("max_heartrate"), "elev": a.get("total_elevation_gain"),
                      "kcal": a.get("calories"),
                      "gear": (a.get("gear") or {}).get("name") if isinstance(
                          a.get("gear"), dict) else None}))
                 for a in acts if a.get("id")])
    sync_plan(user_id, conn, today)
    return len(wellness) + len(acts)


def maybe_sync(user_id: str, now: datetime) -> bool:
    """At most once an hour per user (pages and the 15-minute tick call this)."""
    if store.get_secret(user_id, "intervals") is None:
        return False
    if store.mark_once(user_id, f"sync:{now:%H}", now.date()):
        try:
            sync(user_id, now.date())
            return True
        except intervals.IntervalsError as e:
            log.info("sync failed for %s: %s", user_id, e)
    return False


def sync_plan(user_id: str, conn, today: date) -> int:
    """Planned workouts on the intervals.icu calendar (a coach, TrainingPeaks, a plan) become
    'planned_workout' logs with source 'intervals'. Our own applied sessions are skipped."""
    first, last = today - timedelta(days=1), today + timedelta(days=14)
    events = [e for e in intervals.get_events(conn, first, last) if e.get("category") == "WORKOUT"]
    with connection() as c:
        ours = {r["e"] for r in c.execute(
            "select intervals_event_id as e from proposals where user_id = %s and "
            "intervals_event_id is not null", (user_id,)).fetchall()}
        c.execute("delete from logs where user_id = %s and kind = 'planned_workout' and "
                  "data->>'source' = 'intervals' and day between %s and %s",
                  (user_id, first, last))
    n = 0
    for e in events:
        if str(e.get("id")) in ours or not e.get("start_date_local"):
            continue
        mins = round((e.get("moving_time") or 0) / 60)
        desc = (e.get("name") or e.get("type") or "Workout") + (f" · {mins} min" if mins else "")
        store.add_log(user_id, "planned_workout", date.fromisoformat(e["start_date_local"][:10]),
                      {"description": desc[:200], "activity_type": e.get("type"),
                       "source": "intervals", "event_id": e.get("id")})
        n += 1
    return n


def pain_trend(user_id: str, today: date, days: int = 90) -> list[dict]:
    """Pain 0–10 per body part from the logs: points, the latest score and a 14-day trend."""
    with connection() as c:
        rows = c.execute(
            "select day, data from logs where user_id = %s and kind in ('pain', 'symptom') and "
            "day between %s and %s and data ? 'pain_score' order by day",
            (user_id, today - timedelta(days=days), today)).fetchall()
    parts: dict[str, list] = {}
    for r in rows:
        where = (r["data"].get("pain_location") or "unspecified").strip().lower()
        try:
            parts.setdefault(where, []).append((r["day"], float(r["data"]["pain_score"])))
        except (TypeError, ValueError):
            continue
    out = []
    for where, pts in parts.items():
        recent = [v for d, v in pts if d > today - timedelta(days=7)]
        before = [v for d, v in pts if today - timedelta(days=14) < d <= today - timedelta(days=7)]
        trend = None
        if recent and before:
            diff = mean(recent) - mean(before)
            trend = "worse" if diff >= 1 else "better" if diff <= -1 else "same"
        out.append({"where": where, "points": pts, "latest": pts[-1][1],
                    "latest_day": pts[-1][0], "max": max(v for _, v in pts), "trend": trend,
                    "n": len(pts)})
    return sorted(out, key=lambda p: p["latest_day"], reverse=True)


def _is_shoe(f: dict) -> bool:
    d = f.get("details") or {}
    text = (str(d.get("type", "")) + " " + f["text"]).lower()
    return bool(d.get("retire_km")) or any(w in text for w in ("shoe", "кросів", "кросовк"))


def gear_km(user_id: str, items: list[dict]) -> dict[int, dict]:
    """Running km per shoe: the km it had when added + runs since then. A run with a gear name
    (from intervals.icu) goes to the shoe whose name matches; others go to the newest shoe."""
    shoes = sorted([f for f in items if f["category"] == "gear" and f["status"] == "active"
                    and _is_shoe(f)], key=lambda f: f["created_at"])
    if not shoes:
        return {}
    first = min(f["created_at"].date() for f in shoes)
    runs = [a for a in activities(user_id, first, date.today()) if a["type"] in RUN_TYPES]
    out = {}
    for f in shoes:
        d = f.get("details") or {}
        try:
            start = float(d.get("km_start") or d.get("km") or 0)
            retire = float(d.get("retire_km") or 600)
        except (TypeError, ValueError):
            start, retire = 0.0, 600.0
        out[f["id"]] = {"km": start, "retire": retire, "since": f["created_at"].date()}
    newest = shoes[-1]["id"]
    for a in runs:
        g = (a.get("gear") or "").lower()
        owner = next((f["id"] for f in shoes if g and (g in f["text"].lower() or
                                                       f["text"].lower() in g)), None)
        owner = owner or (newest if not g else None)
        if owner and a["day"] >= out[owner]["since"].isoformat():
            out[owner]["km"] += a.get("km") or 0
    for v in out.values():
        v["km"] = round(v["km"])
        v["pct"] = min(100, round(100 * v["km"] / v["retire"])) if v["retire"] else 0
    return out


def series(user_id: str, first: date, last: date) -> list[dict]:
    with connection() as c:
        rows = c.execute("select day, data from wellness_daily where user_id = %s and day "
                         "between %s and %s order by day", (user_id, first, last)).fetchall()
    out = []
    for r in rows:
        d = dict(r["data"])
        d.pop("v", None)
        if d.get("sleep_h"):
            d["sleep_h"] = d["sleep_h"] / 3600
        if isinstance(d.get("fitness"), (int, float)) and isinstance(d.get("fatigue"),
                                                                      (int, float)):
            d["form"] = d["fitness"] - d["fatigue"]
        d = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in d.items()}
        out.append({"day": r["day"].isoformat(), **d})
    return out


def activities(user_id: str, first: date, last: date) -> list[dict]:
    with connection() as c:
        rows = c.execute("select day, type, data from activities where user_id = %s and day "
                         "between %s and %s order by day", (user_id, first, last)).fetchall()
    return [{"day": r["day"].isoformat(), "type": r["type"], **r["data"]} for r in rows]


def _avg(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(mean(vals), 1) if vals else None


def latest(rows: list[dict], key: str):
    for r in reversed(rows):
        if r.get(key) is not None:
            return r[key], r["day"]
    return None, None


def summary(user_id: str, today: date, days: int = 30) -> dict:
    rows = series(user_id, today - timedelta(days=days), today)
    last7 = [r for r in rows if r["day"] > (today - timedelta(days=7)).isoformat()]
    prev = [r for r in rows if r["day"] <= (today - timedelta(days=7)).isoformat()]
    keys = ["hrv", "resting_hr", "sleep_h", "weight_kg", "fitness", "fatigue"]
    out = {"days": days, "synced_through": rows[-1]["day"] if rows else None,
           "last_7_days_avg": {k: _avg(last7, k) for k in keys},
           f"previous_{days - 7}_days_avg": {k: _avg(prev, k) for k in keys}}
    vo2, vo2_day = latest(rows, "vo2max")
    out["vo2max"] = {"value": vo2, "date": vo2_day}
    acts = activities(user_id, today - timedelta(days=days), today)
    by_type: dict[str, dict] = {}
    for a in acts:
        t = by_type.setdefault(a["type"] or "Other", {"sessions": 0, "km": 0, "minutes": 0})
        t["sessions"] += 1
        t["km"] = round(t["km"] + (a.get("km") or 0), 1)
        t["minutes"] += a.get("minutes") or 0
    out["training_by_type"] = by_type
    from app import patterns
    out["patterns_from_own_log"] = [p["text"] for p in patterns.find(user_id, today)]
    out["pain"] = [{"where": p["where"], "latest": p["latest"], "trend": p["trend"]}
                   for p in pain_trend(user_id, today, 30)]
    return out
