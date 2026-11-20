"""C13 Day windows (code, no LLM): calendar blocks for a day -> busy and free windows, the longest
free window, the latest bedtime and how much sleep tomorrow's first event leaves.

Input: blocks ({starts_at, ends_at (aware datetimes), all_day}), the day, the person's time zone,
wake/bed times from Settings (default 07:00-22:30), sleep target (default 8 h).
Buffers: 30 min around each event, 60 min before the first event of the day (getting there).
All-day events are day notes, never busy.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.db import connection

DEFAULTS = {"usual_training_time": "07:00", "wake_time": "07:00", "bedtime": "22:30"}
BUFFER_MIN, FIRST_BUFFER_MIN, MIN_FREE_MIN = 30, 60, 10


def prefs_times(user_id: str) -> dict:
    """Wake/bed/training time from Settings. The columns come with B1 (migration 008); until they
    exist, or when empty, the defaults apply (07:00 / 07:00 / 22:30)."""
    with connection() as c:
        row = c.execute("select * from user_prefs where user_id = %s", (user_id,)).fetchone()
    row = row or {}
    return {k: _hhmm(row.get(k)) or v for k, v in DEFAULTS.items()}


def _hhmm(v) -> str | None:
    try:
        h, m = (int(x) for x in str(v).split(":")[:2])
        return f"{h:02d}:{m:02d}" if 0 <= h < 24 and 0 <= m < 60 else None
    except (TypeError, ValueError):
        return None


def _at(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), tz)


def _merge(spans: list[list[datetime]]) -> list[list[datetime]]:
    out: list[list[datetime]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _busy(blocks: list[dict], tz: ZoneInfo) -> list[list[datetime]]:
    return sorted([[b["starts_at"].astimezone(tz), b["ends_at"].astimezone(tz)]
                   for b in blocks if not b.get("all_day")])


def windows(blocks: list[dict], day: date, tz: ZoneInfo, wake: str = "07:00",
            bed: str = "22:30", sleep_target_h: float = 8.0,
            tomorrow: list[dict] | None = None) -> dict:
    """C13 for one day. `tomorrow` = the next day's blocks (for the sleep check)."""
    fmt = "%H:%M"
    day_start, day_end = _at(day, wake, tz), _at(day, bed, tz)
    raw = [[s, e] for s, e in _busy(blocks, tz) if e > s and s < day_end + timedelta(hours=3)
           and e > datetime.combine(day, time.min, tz)]
    busy = _merge([[max(s, datetime.combine(day, time.min, tz)), e] for s, e in raw])
    padded = []
    for i, (s, e) in enumerate(busy):
        before = FIRST_BUFFER_MIN if i == 0 else BUFFER_MIN
        padded.append([s - timedelta(minutes=before), e + timedelta(minutes=BUFFER_MIN)])
    padded = _merge(padded)

    free, cursor = [], day_start
    for s, e in padded + [[day_end, day_end]]:
        s, e = max(s, day_start), min(e, day_end)
        if s > cursor and (s - cursor) >= timedelta(minutes=MIN_FREE_MIN):
            free.append([cursor, s])
        cursor = max(cursor, e)
    free = [w for w in free if w[1] > w[0]]

    warnings, aim_bed = [], None
    usual_bed = day_end
    last_end = max((e for _s, e in busy), default=None)
    earliest_bed = max(usual_bed, last_end + timedelta(minutes=BUFFER_MIN)) if last_end else \
        usual_bed
    next_day = day + timedelta(days=1)
    next_wake = _at(next_day, wake, tz)
    first_tomorrow = None
    tb = [b for b in _busy(tomorrow or [], tz) if b[0].date() == next_day]
    if tb:
        first_tomorrow = tb[0][0]
        next_wake = min(next_wake, first_tomorrow - timedelta(minutes=FIRST_BUFFER_MIN))
    bedtime_latest = next_wake - timedelta(hours=sleep_target_h)
    sleep_h = round(max(0.0, (next_wake - earliest_bed).total_seconds() / 3600), 1)
    if sleep_h < sleep_target_h - 0.5:
        late = bool(last_end) and earliest_bed > usual_bed
        why = (f"the {last_end:{fmt}} event end" if late
               else f"the usual {usual_bed:{fmt}} bedtime")
        reason = f" for the {first_tomorrow:{fmt}} start" if first_tomorrow else ""
        aim = max(bedtime_latest, earliest_bed) if late else bedtime_latest
        aim_bed = aim.strftime(fmt)
        warnings.append(f"Only {sleep_h:g} h possible between {why} and the "
                        f"{next_wake:{fmt}} wake{reason}: aim to be in bed by {aim:{fmt}}")
    longest = max((int((e - s).total_seconds() // 60) for s, e in free), default=0)
    if busy and longest < 30:
        warnings.append("No free window of 30 min or more between wake and bedtime")
    return {
        "date": day.isoformat(),
        "busy": [[s.strftime(fmt), e.strftime(fmt)] for s, e in busy],
        "free": [[s.strftime(fmt), e.strftime(fmt), int((e - s).total_seconds() // 60)]
                 for s, e in free],
        "longest_free_min": longest,
        "bedtime_latest": bedtime_latest.strftime(fmt),
        "sleep_possible_h": sleep_h,
        "first_event_tomorrow": first_tomorrow.strftime(fmt) if first_tomorrow else None,
        "sleep_warning_bed": aim_bed,  # set only when sleep_possible_h < target - 0.5
        "warnings": warnings,
    }


def fits(w: dict, start: str, minutes: float) -> bool:
    """True when [start, start + minutes] lies inside one free window."""
    s = _mins(start)
    if s is None:
        return False
    return any(_mins(a) <= s and s + minutes <= _mins(b) for a, b, _m in w["free"])


def _mins(hhmm: str) -> int | None:
    v = _hhmm(hhmm)
    if v is None:
        return None
    h, m = (int(x) for x in v.split(":"))
    return h * 60 + m


def for_user(user_id: str, day: date, tz: ZoneInfo, sleep_target_h: float = 8.0) -> dict | None:
    """C13 from the stored blocks, or None without a connected calendar."""
    from app import calendar
    blocks = calendar.blocks_for_day(user_id, day, tz)
    if blocks is None:
        return None
    p = prefs_times(user_id)
    tomorrow = calendar.blocks_for_day(user_id, day + timedelta(days=1), tz) or []
    return windows(blocks, day, tz, p["wake_time"], p["bedtime"], sleep_target_h, tomorrow)


def coach_summary(user_id: str, day: date, tz: ZoneInfo) -> dict | None:
    """Agent context: today's and tomorrow's busy summary and C13 warnings. Titles only when the
    person turned on "Show event names to the coach" (they are null in the table otherwise)."""
    from app import calendar
    w = for_user(user_id, day, tz)
    if w is None:
        return None
    out = {}
    for label, d in (("today", day), ("tomorrow", day + timedelta(days=1))):
        blocks = [b for b in calendar.blocks_for_day(user_id, d, tz) or [] if not b["all_day"]]
        if not blocks:
            out[label] = "free (no events)"
            continue
        first, last = blocks[0]["starts_at"].astimezone(tz), blocks[-1]["ends_at"].astimezone(tz)
        text = f"busy {first:%H:%M}–{last:%H:%M}, {len(blocks)} blocks"
        names = [f"{b['starts_at'].astimezone(tz):%H:%M} {b['title']}" for b in blocks
                 if b["title"]]
        out[label] = text + (f" ({'; '.join(names)})" if names else "")
    out["free_today"] = [f"{a}–{b}" for a, b, _m in w["free"]]
    out["warnings"] = w["warnings"]
    return out


STRIP_FROM, STRIP_TO = 6 * 60, 23 * 60  # the Today strip shows 06:00-23:00


def strip(w: dict, start: str | None = None, minutes: float = 0) -> dict:
    """Bars for the Today "Your day" strip as % of 06-23 h: busy blocks and the planned session."""
    span = STRIP_TO - STRIP_FROM

    def bar(a: int, b: int, label: str) -> dict | None:
        a, b = max(a, STRIP_FROM), min(b, STRIP_TO)
        if b <= a:
            return None
        return {"left": round((a - STRIP_FROM) / span * 100, 2),
                "width": round((b - a) / span * 100, 2), "label": label}
    busy = []
    for s, e in w["busy"]:
        a, b = _mins(s), _mins(e)
        b = b if b > a else 24 * 60  # past midnight
        x = bar(a, b, f"{s}–{e}")
        if x:
            busy.append(x)
    sess = None
    if start and _mins(start) is not None:
        a = _mins(start)
        b = a + int(minutes)
        sess = bar(a, b, f"{start}–{b // 60 % 24:02d}:{b % 60:02d}")
    return {"busy": busy, "session": sess, "warnings": w["warnings"]}


def fit_line(w: dict, start: str | None, minutes: float) -> dict:
    """Training page: 'fits 12:30-13:30', or 'no free window >= N min'."""
    if start and fits(w, start, minutes):
        b = _mins(start) + int(minutes)
        return {"fits": [start, f"{b // 60 % 24:02d}:{b % 60:02d}"]}
    if minutes and w["longest_free_min"] < minutes:
        return {"no_window": int(minutes)}
    return {"longest": w["longest_free_min"]}
