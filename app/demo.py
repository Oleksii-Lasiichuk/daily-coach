"""Sample watch data and the synthetic Demo Athlete used by the evals.

- `uv run python -m app.demo seed` (dev only) creates or resets "Demo Athlete" with a year of
  synthetic watch data, three weeks of logs, goals, gear and habits. `evals/run_e2e.py` uses it.
- intervals.icu is faked for athlete id "demo" only: wellness and activities are generated from
  the date, and "Send to watch" lands in an in-memory calendar. Real athletes are untouched.
  Any user (also in production) can pick "sample watch data" in setup, which connects their own
  account to this fake athlete: synthetic numbers, no network, nothing reaches a real watch.

All numbers are synthetic. Today is made to look like a hard morning (short sleep, low HRV), so
the main demo case has something to react to.
"""

import itertools
import math
import random
import sys
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from psycopg.types.json import Jsonb

from app.config import get_settings

ATHLETE_ID = "demo"
FIREBASE_UID, EMAIL, NAME = "demo-athlete", "demo@daily-coach.local", "Demo Athlete"
TZ = ZoneInfo("Europe/Kyiv")
_calendar: dict[int, dict] = {}  # events created by "Send to watch" in this process
_ids = itertools.count(900001)


def enabled() -> bool:
    return get_settings().env == "dev"


def is_demo(athlete_id: str) -> bool:
    """The simulated intervals.icu athlete (sample watch data)."""
    return athlete_id == ATHLETE_ID


def _today() -> date:
    return datetime.now(TZ).date()


# ---------- fake intervals.icu ----------

def _wellness_day(d: date) -> dict:
    i = (d - date(2026, 1, 1)).days
    r = random.Random(i)
    hard = d == _today()  # a rough night: the main demo case reacts to this
    sleep_h = 5.2 if hard else 7.2 + 0.5 * math.sin(i / 4) + r.gauss(0, 0.45)
    return {"id": d.isoformat(),
            "hrv": 47 if hard else round(62 + 6 * math.sin(i / 6) + r.gauss(0, 3.5)),
            "restingHR": 55 if hard else round(49 + 1.5 * math.sin(i / 9) + r.gauss(0, 1)),
            "sleepSecs": int(sleep_h * 3600),
            "sleepScore": 54 if hard else max(40, min(98, round(80 + r.gauss(0, 7)))),
            "sleepQuality": 2 if hard else r.choice([2, 3, 3, 4]),
            "weight": round(76.4 - 0.008 * (i % 365) + r.gauss(0, 0.25), 1),
            "vo2max": 53, "ctl": round(42 + 6 * math.sin(i / 40) + 0.02 * i, 1),
            "atl": round(46 + 9 * math.sin(i / 3.5) + r.gauss(0, 2), 1),
            "rampRate": round(r.gauss(1.5, 1.2), 1), "steps": 9000 + r.randint(-3000, 4000)}


def _activity_day(d: date) -> list[dict]:
    i = (d - date(2026, 1, 1)).days
    r = random.Random(i + 7777)
    if d >= _today() or d.weekday() in (0, 4):  # Monday and Friday are rest days
        return []
    if d.weekday() == 6:
        km, name = round(16 + 4 * r.random(), 1), "Long run"
    elif d.weekday() == 2:
        km, name = round(9 + 2 * r.random(), 1), "Intervals 5×1 km"
    elif d.weekday() == 3:
        return [{"id": f"demo{i}s", "start_date_local": f"{d}T18:30:00", "type": "WeightTraining",
                 "name": "Strength", "moving_time": 2400, "icu_training_load": 30,
                 "average_heartrate": 112, "calories": 260}]
    else:
        km, name = round(7 + 3 * r.random(), 1), "Easy run"
    pace = 330 if name == "Easy run" else 300
    return [{"id": f"demo{i}", "start_date_local": f"{d}T07:05:00", "type": "Run", "name": name,
             "distance": km * 1000, "moving_time": int(km * pace),
             "icu_training_load": round(km * (6.5 if "Interval" in name else 5)),
             "average_heartrate": 151 if "Interval" in name else 139, "max_heartrate": 178,
             "total_elevation_gain": round(40 + 60 * r.random()), "calories": round(km * 68),
             "gear": {"name": "Hoka Clifton 9"}}]


ATHLETE = {"id": ATHLETE_ID, "sex": "M", "icu_date_of_birth": "1995-04-12",
           "height": 1.80, "icu_weight": 75.4, "icu_resting_hr": 49, "timezone": "Europe/Kyiv",
           "sportSettings": [{"types": ["Run", "TrailRun", "VirtualRun"], "lthr": 171,
                              "max_hr": 192, "hr_zones": [143, 157, 166, 175, 181, 186, 192],
                              "threshold_pace": 3.85},
                             {"types": ["Ride", "VirtualRide"], "ftp": 240, "lthr": 165,
                              "max_hr": 186, "hr_zones": [135, 149, 157, 166, 174, 180, 186]}]}


def _planned(first: date, last: date) -> list[dict]:
    """A plan on the calendar (like Garmin Coach): intervals on Wednesdays and today."""
    out, d = [], first
    while d <= last:
        if d == _today() or (d > _today() and d.weekday() == 2):
            out.append({"id": 800000 + (d - date(2026, 1, 1)).days, "category": "WORKOUT",
                        "start_date_local": f"{d}T00:00:00", "type": "Run",
                        "name": "Intervals 6×800 m", "moving_time": 3300})
        d += timedelta(days=1)
    return out + [e for e in _calendar.values() if first.isoformat() <= e["start_date_local"][:10]
                  <= last.isoformat()]


def fake_request(method: str, path: str, params: dict | None = None,
                 json: dict | None = None) -> httpx.Response:
    """Answers the few intervals.icu calls the app makes, for the demo athlete."""
    req = httpx.Request(method, "https://intervals.icu/api/v1" + path)
    params = params or {}
    if method == "GET" and path.endswith("/wellness"):
        first, last = date.fromisoformat(params["oldest"]), date.fromisoformat(params["newest"])
        body = [_wellness_day(first + timedelta(days=n)) for n in range((last - first).days + 1)]
    elif method == "GET" and path.endswith("/activities"):
        first, last = date.fromisoformat(params["oldest"]), date.fromisoformat(params["newest"])
        body = [a for n in range((last - first).days + 1)
                for a in _activity_day(first + timedelta(days=n))]
    elif method == "GET" and path.endswith("/events"):
        body = _planned(date.fromisoformat(params["oldest"]), date.fromisoformat(params["newest"]))
    elif method == "POST" and path.endswith("/events"):
        eid = next(_ids)
        _calendar[eid] = {"id": eid, **(json or {})}
        body = _calendar[eid]
    elif method == "DELETE" and "/events/" in path:
        _calendar.pop(int(path.rsplit("/", 1)[1]), None)
        body = {}
    else:
        body = ATHLETE
    return httpx.Response(200, json=body, request=req)


# ---------- seed ----------

def _meal(day: date, hour: int, kind: str, text: str, kcal: float, p: float, c: float, f: float,
          foods: list[tuple[str, int]], **extra) -> tuple:
    from app.pipeline.nutrition import NUTRIENTS
    totals = dict.fromkeys(NUTRIENTS, 0.0) | {
        "kcal": kcal, "protein_g": p, "carbs_g": c, "fat_g": f, "fiber_g": round(c * 0.08, 1),
        "sugar_g": round(c * 0.2, 1), "sat_fat_g": round(f * 0.3, 1), "salt_g": 1.4,
        "iron_mg": round(kcal / 160, 1), "calcium_mg": round(kcal * 0.4),
        "potassium_mg": round(kcal * 1.6), "magnesium_mg": round(kcal * 0.15),
        "vit_c_mg": 18, "vit_d_ug": 0.8} | extra
    share = 1 / max(1, len(foods))
    items = [{"name": n, "food": n, "grams": g, **{k: round(v * share, 1) for k, v in
                                                   totals.items()}} for n, g in foods]
    at = datetime(day.year, day.month, day.day, hour, 15, tzinfo=TZ).astimezone(UTC)
    data = {"description": text, "nutrition": {"items": items, "totals": totals, "kcal": kcal,
                                               "protein_g": p, "carbs_g": c, "fat_g": f}}
    return kind, day, data, at


def seed() -> str:
    from app import crypto, health, store
    from app.db import connection
    if not enabled():
        raise SystemExit("The demo athlete is for local runs only (ENV=dev).")
    with connection() as c:
        c.execute("delete from users where firebase_uid = %s", (FIREBASE_UID,))
    user = store.upsert_user(FIREBASE_UID, EMAIL, NAME).id
    store.save_secret(user, "intervals", crypto.encrypt("demo-key"), "demo", ATHLETE_ID)
    from app import intervals
    for k, v in intervals.profile_from_athlete(ATHLETE).items():
        store.set_profile_field(user, k, v, "intervals")
    store.set_time_zone(user, "Europe/Kyiv")
    for k, v in {"sleep_target_h": "8", "diet": "Omnivore", "plan_source": "intervals",
                 "target_weight_kg": "73", "location": {"name": "Lviv", "lat": 49.84,
                                                        "lon": 24.03, "country": "Ukraine"}
                 }.items():
        store.set_profile_field(user, k, v, "user", actor="user")
    today = _today()
    with connection() as c:
        for cat, text, term, until, det in [
            ("race", "Lviv Half Marathon", "long", None,
             {"date": (today + timedelta(days=48)).isoformat(), "distance": "Half marathon",
              "target_time": "1:45:00"}),
            ("goal", "Half marathon under 1:45 this spring", "long", None, {}),
            ("goal", "Get to 73 kg by the race", "long", None, {}),
            ("gear", "Hoka Clifton 9", "long", None, {"type": "shoes", "retire_km": 700}),
            ("gear", "Garmin Forerunner 265", "long", None, {"type": "watch"}),
            ("gear", "Garmin HRM-Pro chest strap", "long", None, {"type": "hrm"}),
            ("injury", "Left knee overload in March 2026, fine now; watch long downhills",
             "long", None, {}),
            ("medication", "Vitamin D 2000 IU each morning", "current",
             today + timedelta(days=40), {}),
            ("preference", "No pork. Likes oatmeal, buckwheat, chicken, cottage cheese",
             "long", None, {}),
            ("preference", "Prefers runs before work, 6:30 to 7:30", "long", None, {}),
            ("life", "Desk job, 8 to 9 hours of sitting", "long", None, {}),
        ]:
            c.execute("insert into facts (user_id, category, text, source, status, term, until, "
                      "details, created_at) values (%s, %s, %s, 'user', 'active', %s, %s, %s, "
                      "now() - interval '30 days')", (user, cat, text, term, until, Jsonb(det)))
    health.sync(user, today)
    logs = []
    for n in range(21, 0, -1):
        d = today - timedelta(days=n)
        logs.append(_meal(d, 8, "meal", "Oatmeal with a banana and honey", 480, 14, 86, 9,
                          [("oatmeal", 250), ("banana", 120)]))
        logs.append(_meal(d, 9, "drink", "Coffee with milk", 70, 4, 6, 3, [("coffee", 250)],
                          caffeine_mg=95))
        logs.append(_meal(d, 13, "meal", "Buckwheat with chicken and salad", 690, 46, 72, 20,
                          [("buckwheat", 200), ("chicken breast", 150), ("salad", 120)]))
        late = n % 6 == 0
        logs.append(_meal(d, 22 if late else 19, "meal", "Pasta with tomato sauce and cheese",
                          760, 26, 112, 20, [("pasta", 230), ("tomato sauce", 120),
                                             ("cheese", 30)]))
        if d.weekday() in (4, 5) and n > 1:  # yesterday is left to the demo message
            kind, day, data, at = _meal(d, 21, "alcohol", "Two beers, 0.5 L each", 430, 3, 36, 0,
                                        [("beer", 1000)], alcohol_g=40)
            logs.append((kind, day, data | {"alcohol_drinks": 2}, at))
    for n, score in [(12, 2), (8, 3), (5, 3), (2, 2)]:
        logs.append(("pain", today - timedelta(days=n), {
            "description": f"Left knee {score}/10 after the run", "pain_location": "left knee",
            "pain_score": score}, None))
    for kind, day, data, at in logs:
        store.add_log(user, kind, day, data, at)
    for h in ["Stretching 10 min", "2 L of water", "In bed by 23:00"]:
        store.add_habit(user, h)
    for n in range(7, 0, -1):
        d = today - timedelta(days=n)
        snap = intervals.day_snapshot(user, d)
        t, b = snap.get("today") or {}, snap.get("baseline_7d") or {}
        hrv, base = t.get("hrv"), b.get("hrv")
        kind = ("easy" if d.weekday() in (5, 0) else "push" if d.weekday() == 2 else "normal")
        sleep = t.get("sleep_h")
        reasons = [{"text": f"HRV {hrv} vs usual {base}.", "evidence": f"HRV {hrv}"},
                   {"text": f"Slept {sleep} h.", "evidence": f"Sleep {sleep} h"}]
        if d.weekday() in (5, 6):
            reasons.append({"text": "Two beers the evening before.", "evidence": "2 beers"})
        store.save_assessment(user, d, kind, 0.75, reasons,
                              {"summary": f"{kind.capitalize()} day from sleep and HRV."}, None)
    _labs(user, today)
    seed_money(user, today)
    store.set_setup_step(user, 6)
    return user


def _labs(user: str, today: date) -> None:
    """Two synthetic blood tests (B3): ferritin low in the first, recovering in the second."""
    from app.pipeline import labs
    from app.pipeline.labs import LabSheet, PrintedRow
    for days_ago, values in [(170, {"Ferritin": "18", "Haemoglobin": "13.4", "Vitamin D": "21"}),
                             (45, {"Ferritin": "34", "Haemoglobin": "14.1", "Vitamin D": "38"})]:
        rows = [("Ferritin", values["Ferritin"], "ng/mL", "30 - 400"),
                ("Haemoglobin", values["Haemoglobin"], "g/dL", "13.0 - 17.0"),
                ("Vitamin D (25-OH)", values["Vitamin D"], "ng/mL", "30 - 100"),
                ("TSH", "2.1", "mIU/L", "0.4 - 4.0"), ("Glucose", "4.9", "mmol/L", "3.9 - 5.6"),
                ("CRP", "<0.5", "mg/L", "< 5")]
        sheet = LabSheet(lab="Demo Lab", taken_on=None, rows=[PrintedRow(
            name_as_printed=n, value_as_printed=v, unit_as_printed=u, ref_as_printed=r)
            for n, v, u, r in rows])
        labs.save(user, sheet, labs.normalise(sheet), today - timedelta(days=days_ago),
                  "demo-lab.pdf", None)
# Synthetic card payments (plan 11 B4): fake merchants and amounts, ~4 months, with delivery
# about 2× the usual this month so the Money page and the coach have a flag to show.
DEMO_MERCHANTS = [("Сільпо", 5411, 650, 9), ("ATB", 5411, 280, 6), ("Glovo", 5814, 390, 3),
                  ("Aroma Kava", 5814, 85, 10), ("Puzata Khata", 5812, 240, 3),
                  ("Bolt", 4121, 160, 3), ("Аптека Доброго Дня", 5912, 310, 1),
                  ("Kyivstar", 4814, 250, 1), ("Netflix.com", 4899, 249, 1),
                  ("Sportpit Lviv", 5499, 520, 1), ("WOG", 5541, 1200, 1)]


def seed_money(user: str, today: date) -> None:
    from app import money, store
    r = random.Random(11)
    start = (today.replace(day=1) - timedelta(days=95)).replace(day=1)
    rows, d = [], start
    while d <= today:
        for name, mcc, avg, per_month in DEMO_MERCHANTS:
            boost = 2.2 if name == "Glovo" and d.month == today.month else 1
            if r.random() < per_month * boost / 30:
                amount = round(avg * r.uniform(0.6, 1.4) * 100)
                at = datetime.combine(d, datetime.min.time(), TZ).replace(
                    hour=r.randint(8, 21), minute=r.randint(0, 59)).astimezone(UTC)
                rows.append((name, mcc, -amount, at))
        if d.day == 5:
            rows.append(("Salary", 4829, 4_500_000, datetime.combine(d, datetime.min.time(),
                                                                       TZ).astimezone(UTC)))
        d += timedelta(days=1)
    rows.append(("Lviv Half Marathon registration", 7941, -90000,
                 datetime.now(UTC) - timedelta(days=20)))
    for i, (name, mcc, amount, at) in enumerate(rows):
        money.upsert_monobank(user, {"ext_id": f"demo-{i}", "account_id": "demo-black",
                                     "at": at, "amount_minor": amount, "currency": 980,
                                     "mcc": None if amount > 0 else mcc, "original_mcc": None,
                                     "description": "Transfer" if amount > 0 else name,
                                     "hold": False})
    money.categorise_pending(user, limit=2000)
    u = store.get_user(user)
    store.set_tracks(user, sorted(set(u.tracks or []) | {"training", "money"}))


def user_id() -> str | None:
    from app.db import connection
    with connection() as c:
        r = c.execute("select id from users where firebase_uid = %s", (FIREBASE_UID,)).fetchone()
    return str(r["id"]) if r else None


if __name__ == "__main__":
    if sys.argv[1:] == ["seed"]:
        print("Demo Athlete ready:", seed())
    else:
        print("usage: uv run python -m app.demo seed")


# ---------- synthetic calendar (B2) ----------
# "Connect calendar" with one of these links reads a generated ICS instead of the network, so the
# test account and the UI check never touch a real calendar. Three styles, like the real feeds:
# Google (UTC "Z" times + X-WR-TIMEZONE), iCloud (VTIMEZONE + TZID), Outlook (busy-only titles).
DEMO_CALENDAR_HOST = "calendar.demo.invalid"
DEMO_CALENDARS = {f"https://{DEMO_CALENDAR_HOST}/{k}.ics": k for k in ("google", "icloud",
                                                                        "outlook")}
_KYIV_VTZ = """BEGIN:VTIMEZONE
TZID:Europe/Kyiv
BEGIN:STANDARD
DTSTART:19701025T040000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
TZOFFSETFROM:+0300
TZOFFSETTO:+0200
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700329T030000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
TZOFFSETFROM:+0200
TZOFFSETTO:+0300
END:DAYLIGHT
END:VTIMEZONE"""


def is_demo_calendar(url: str) -> bool:
    return url in DEMO_CALENDARS


def calendar_ics(url: str = "") -> bytes:
    """Today: standup, meetings until 18:30 with a lunch gap; a 22:00 call; tomorrow an 07:00
    flight; a weekly yoga class; an all-day birthday. All synthetic."""
    style = DEMO_CALENDARS.get(url, "icloud")
    today = _today()
    t1 = today + timedelta(days=1)

    def local(d: date, hhmm: str) -> str:
        h, m = hhmm.split(":")
        if style == "google":
            dt = datetime(d.year, d.month, d.day, int(h), int(m), tzinfo=TZ).astimezone(UTC)
            return f":{dt:%Y%m%dT%H%M%S}Z"
        return f";TZID=Europe/Kyiv:{d:%Y%m%d}T{h}{m}00"

    def ev(uid: str, d: date, start: str, end: str, title: str, extra: str = "") -> str:
        name = "Busy" if style == "outlook" else title
        return (f"BEGIN:VEVENT\nUID:{uid}@demo\nDTSTAMP:20260101T000000Z\n"
                f"DTSTART{local(d, start)}\nDTEND{local(d, end)}\nSUMMARY:{name}\n"
                f"{extra}END:VEVENT")

    monday = today - timedelta(days=today.weekday())
    events = [
        ev("standup", monday, "09:30", "09:45", "Team standup",
           "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\n"),
        ev("yoga", monday + timedelta(days=2), "19:00", "20:00", "Yoga class",
           "RRULE:FREQ=WEEKLY\n"),
        ev("m1", today, "10:00", "12:00", "Planning"),
        ev("m2", today, "13:15", "15:30", "Client workshop"),
        ev("m3", today, "16:00", "18:30", "1:1s"),
        ev("call", today, "22:00", "23:00", "Call with the US team"),
        ev("flight", t1, "07:00", "09:30", "Flight to Lviv"),
        "BEGIN:VEVENT\nUID:bday@demo\nDTSTAMP:20260101T000000Z\n"
        f"DTSTART;VALUE=DATE:{t1:%Y%m%d}\nDTEND;VALUE=DATE:{t1 + timedelta(days=1):%Y%m%d}\n"
        "SUMMARY:Birthday\nTRANSP:TRANSPARENT\nEND:VEVENT",
    ]
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//Daily Coach demo//{style}//EN"]
    if style == "google":
        head.append("X-WR-TIMEZONE:Europe/Kyiv")
    else:
        head.append(_KYIV_VTZ)
    return ("\r\n".join(head + events + ["END:VCALENDAR"]).replace("\n", "\r\n")
            .replace("\r\r\n", "\r\n") + "\r\n").encode()
