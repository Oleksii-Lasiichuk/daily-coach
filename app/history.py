"""Day-by-day memory: a short, code-written digest of each past day (no LLM, so it can't drift
from what was logged). Used in prompts (recent days) and by the History calendar."""

from datetime import date, timedelta

from app.db import connection

KIND_WORDS = {"meal": "ate", "drink": "drank", "alcohol": "alcohol", "sleep": "sleep",
              "mood": "mood", "pain": "pain", "symptom": "symptom", "medication": "took",
              "activity": "trained", "planned_workout": "Garmin planned", "note": "note"}


def days_between(user_id: str, first: date, last: date) -> dict[date, dict]:
    """{day: {type, summary, logs[], session}} for days that have anything."""
    out: dict[date, dict] = {}
    with connection() as c:
        for a in c.execute("select day, day_type, inputs->>'summary' as summary "
                           "from day_assessments where user_id = %s and day between %s and %s",
                           (user_id, first, last)):
            out.setdefault(a["day"], {"logs": []}).update(type=a["day_type"], summary=a["summary"])
        for lg in c.execute("select day, kind, data from logs where user_id = %s and day between "
                            "%s and %s order by day, coalesce(occurred_at, created_at)",
                            (user_id, first, last)):
            out.setdefault(lg["day"], {"logs": []})["logs"].append(lg)
        for p in c.execute(
                """select distinct on (day) day, status, workout->>'name' as name
                   from proposals where user_id = %s and day between %s and %s
                     and status in ('applied', 'proposed')
                   order by day, (status = 'applied') desc, id desc""", (user_id, first, last)):
            out.setdefault(p["day"], {"logs": []})["session"] = (
                p["name"] + (" (applied)" if p["status"] == "applied" else " (suggested)"))
    return out


def digest(day: date, d: dict) -> str:
    """'Fri 13 Nov: easy. alcohol 4 пива (6 drinks); sleep 5 h. Session: …'"""
    parts = []
    for lg in d.get("logs", []):
        data = lg["data"]
        text = f"{KIND_WORDS.get(lg['kind'], lg['kind'])} {data.get('description', '')}".strip()
        n = data.get("nutrition") or {}
        kcal = n.get("kcal") or (n.get("totals") or {}).get("kcal")
        if kcal:
            text += f" {round(kcal)} kcal"
        if data.get("alcohol_drinks"):
            text += f" ({data['alcohol_drinks']:g} drinks)"
        if data.get("pain_score") is not None:
            text += f" {data['pain_score']}/10"
        parts.append(text)
    head = f"{day:%a %d %b}" + (f": {d['type']}" if d.get("type") else "")
    body = "; ".join(parts)
    tail = f" Session: {d['session']}." if d.get("session") else ""
    return f"{head}. {body}.{tail}".replace(". .", ".")


def day_chips(d: dict) -> dict:
    """Short numbers for one day in the Journal: kcal, sleep, drinks, worst pain, session."""
    kcal = sleep = drinks = 0.0
    pain = None
    for lg in d.get("logs", []):
        data = lg["data"]
        n = data.get("nutrition") or {}
        kcal += n.get("kcal") or (n.get("totals") or {}).get("kcal") or 0
        sleep = data.get("sleep_hours") or sleep
        drinks += data.get("alcohol_drinks") or 0
        if data.get("pain_score") is not None:
            pain = max(pain or 0, float(data["pain_score"]))
    return {"type": d.get("type"), "kcal": round(kcal), "sleep": sleep, "drinks": drinks,
            "pain": pain, "session": d.get("session"), "n": len(d.get("logs", []))}


def recent_digests(user_id: str, today: date, days: int = 14) -> list[str]:
    """Digests for the days before today (newest last), for prompts."""
    data = days_between(user_id, today - timedelta(days=days), today - timedelta(days=1))
    return [digest(d, data[d]) for d in sorted(data)]


def week_numbers(user_id: str, start: date) -> dict:
    """One week (Mon–Sun from `start`) in numbers, computed in code."""
    end = start + timedelta(days=6)
    with connection() as c:
        acts = c.execute("select data from activities where user_id = %s and day between %s "
                         "and %s", (user_id, start, end)).fetchall()
        well = c.execute("select data from wellness_daily where user_id = %s and day between "
                         "%s and %s", (user_id, start, end)).fetchall()
        logs = c.execute("select day, kind, data from logs where user_id = %s and day between "
                         "%s and %s", (user_id, start, end)).fetchall()

    def avg(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else None

    meal_days: dict = {}
    for lg in logs:
        n = (lg["data"].get("nutrition") or {}).get("totals") or {}
        if n:
            meal_days[lg["day"]] = meal_days.get(lg["day"], 0) + n.get("kcal", 0)
    pains = [lg["data"].get("pain_score") for lg in logs if lg["kind"] == "pain"]
    return {
        "sessions": len(acts),
        "km": round(sum(a["data"].get("km") or 0 for a in acts), 1),
        "hours": round(sum(a["data"].get("minutes") or 0 for a in acts) / 60, 1),
        "load": round(sum(a["data"].get("load") or 0 for a in acts)),
        "sleep_h": avg([(w["data"].get("sleep_h") or 0) / 3600 or None for w in well]),
        "hrv": avg([w["data"].get("hrv") for w in well]),
        "alcohol_days": len({lg["day"] for lg in logs if lg["kind"] == "alcohol"}),
        "kcal": avg(list(meal_days.values())),
        "pain_max": max([p for p in pains if isinstance(p, (int, float))], default=None),
    }


def week_review(user_id: str, today: date) -> dict:
    start = today - timedelta(days=today.weekday())
    return {"start": start, "this": week_numbers(user_id, start),
            "last": week_numbers(user_id, start - timedelta(days=7))}
