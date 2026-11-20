"""B2 calendar through an iCal (ICS) link: fetch, parse into busy blocks, sync in the tick.

The ICS URL is a credential (anyone with it can read the calendar): stored encrypted in
user_secrets (provider 'ical'), never logged (only the host), never sent to an LLM. Only start,
end, all-day and, if the person allowed it, the title are kept; never location, attendees or
descriptions. Recurring events, edited occurrences and time zones are expanded by
`recurring-ical-events` (on top of `icalendar`), because getting them wrong by hand would silently
put runs on top of meetings.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events

from app import crypto, store
from app.db import connection

log = logging.getLogger("calendar")
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 10
MAX_OCCURRENCES = 2000
LONG_EVENT = timedelta(hours=16)  # longer non-all-day events ("Vacation") are day notes
DAYS_BACK, DAYS_AHEAD = 1, 14
EVERY, AFTER_ERROR = timedelta(minutes=30), timedelta(hours=2)


class CalendarError(Exception):
    """A message the person can act on (shown on the card / in Settings)."""


@dataclass
class Block:
    starts_at: datetime  # UTC
    ends_at: datetime  # UTC
    all_day: bool
    busy: bool
    title: str | None = None


# --- fetch ---------------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    p = urlparse(url)
    if p.scheme != "https" or not p.netloc:
        raise CalendarError("This link isn't a calendar")
    return url


def host(url: str) -> str:
    """The only part of the URL that may be logged."""
    return urlparse(url).netloc


def fetch(url: str, client: httpx.Client | None = None) -> bytes:
    """Raw ICS bytes. Limits: 10 s, 5 MB, must look like a calendar."""
    url = normalize_url(url)
    from app import demo
    if demo.is_demo_calendar(url):
        return demo.calendar_ics(url)
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S, follow_redirects=True)
    try:
        with client.stream("GET", url, headers={"User-Agent": "DailyCoach/1.0"}) as r:
            if r.status_code in (401, 403, 404, 410):
                raise CalendarError("Google says the link is wrong — copy it again")
            if r.status_code >= 400:
                raise CalendarError("Can't reach the calendar")
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise CalendarError("The calendar is too big (over 5 MB)")
    except httpx.HTTPError as e:
        log.info("calendar fetch failed for host %s: %s", host(url), type(e).__name__)
        raise CalendarError("Can't reach the calendar") from None
    finally:
        if own:
            client.close()
    if b"BEGIN:VCALENDAR" not in body[:2048].upper():
        raise CalendarError("This link isn't a calendar")
    return body


# --- parse ---------------------------------------------------------------------------------

def _as_utc(v, tz: ZoneInfo) -> datetime:
    """A DTSTART/DTEND value as UTC; floating times are read in the person's time zone."""
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=tz)).astimezone(UTC)
    return datetime.combine(v, time.min, tz).astimezone(UTC)  # a date (all-day)


def parse(ics: bytes, tz: ZoneInfo, start: datetime, end: datetime,
          keep_titles: bool = False) -> list[Block]:
    """Occurrences overlapping [start, end) as blocks, sorted by start."""
    try:
        cal = icalendar.Calendar.from_ical(ics)
        events = recurring_ical_events.of(cal, skip_bad_series=True).between(start, end)
    except (ValueError, KeyError, IndexError) as e:
        raise CalendarError("This link isn't a calendar") from e
    blocks = []
    for i, ev in enumerate(events):
        if i >= MAX_OCCURRENCES:
            break
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        if str(ev.get("TRANSP", "")).upper() == "TRANSPARENT":
            continue
        dtstart = ev.get("DTSTART")
        if dtstart is None:
            continue
        s = dtstart.dt
        all_day = not isinstance(s, datetime)
        dtend = ev.get("DTEND")
        if dtend is not None:
            e = dtend.dt
        elif ev.get("DURATION") is not None:
            e = s + ev["DURATION"].dt
        else:  # RFC 5545: no end = one day for dates, zero length for times
            e = s + timedelta(days=1) if all_day else s
        s_utc, e_utc = _as_utc(s, tz), _as_utc(e, tz)
        if e_utc <= s_utc:
            continue
        busy = not all_day and e_utc - s_utc <= LONG_EVENT
        title = str(ev.get("SUMMARY", "")).strip()[:120] or None if keep_titles else None
        blocks.append(Block(s_utc, e_utc, all_day or not busy, busy, title))
    return sorted(blocks, key=lambda b: b.starts_at)


def window(now: datetime) -> tuple[datetime, datetime]:
    day = now.date()
    tz = now.tzinfo
    return (datetime.combine(day - timedelta(days=DAYS_BACK), time.min, tz),
            datetime.combine(day + timedelta(days=DAYS_AHEAD + 1), time.min, tz))


# --- storage -------------------------------------------------------------------------------

def feed(user_id: str) -> dict | None:
    with connection() as c:
        return c.execute("select * from calendar_feeds where user_id = %s",
                         (user_id,)).fetchone()


def save_url(user_id: str, url: str) -> None:
    url = normalize_url(url)
    tail = url.split("?")[0].removesuffix(".ics")  # every link ends in .ics: show what differs
    store.save_secret(user_id, "ical", crypto.encrypt(url), crypto.last4(tail), host(url))
    with connection() as c:
        c.execute("insert into calendar_feeds (user_id) values (%s) on conflict (user_id) do "
                  "update set next_at = now(), last_error = null", (user_id,))


def set_titles(user_id: str, on: bool) -> None:
    with connection() as c:
        c.execute("update calendar_feeds set show_titles = %s, next_at = now() "
                  "where user_id = %s", (on, user_id))
        if not on:
            c.execute("update calendar_blocks set title = null where user_id = %s", (user_id,))


def remove(user_id: str) -> None:
    store.delete_secret(user_id, "ical")
    with connection() as c:
        c.execute("delete from calendar_blocks where user_id = %s", (user_id,))
        c.execute("delete from calendar_feeds where user_id = %s", (user_id,))


def blocks_between(user_id: str, start: datetime, end: datetime) -> list[dict]:
    with connection() as c:
        return c.execute("select starts_at, ends_at, all_day, title from calendar_blocks "
                         "where user_id = %s and ends_at > %s and starts_at < %s "
                         "order by starts_at", (user_id, start, end)).fetchall()


def blocks_for_day(user_id: str, day: date, tz: ZoneInfo) -> list[dict] | None:
    """The day's blocks, or None when the person has no calendar connected."""
    if not feed(user_id):
        return None
    start = datetime.combine(day, time.min, tz)
    return blocks_between(user_id, start, start + timedelta(days=1))


# --- sync ----------------------------------------------------------------------------------

def sync(user_id: str, now: datetime | None = None) -> int:
    """Fetch, parse and replace the person's blocks for the window. Returns the event count."""
    user = store.get_user(user_id)
    tz = ZoneInfo(user.time_zone)
    now = (now or datetime.now(tz)).astimezone(tz)
    secret = store.get_secret(user_id, "ical")
    f = feed(user_id)
    if not secret or not f:
        return 0
    try:
        ics = fetch(crypto.decrypt(secret["ciphertext"]))
        start, end = window(now)
        blocks = parse(ics, tz, start, end, keep_titles=f["show_titles"])
    except CalendarError as e:
        with connection() as c:
            c.execute("update calendar_feeds set last_error = %s, next_at = %s "
                      "where user_id = %s", (str(e), now + AFTER_ERROR, user_id))
        raise
    with connection() as c, c.transaction():
        c.execute("delete from calendar_blocks where user_id = %s", (user_id,))
        for b in blocks:
            c.execute("insert into calendar_blocks (user_id, starts_at, ends_at, all_day, title) "
                      "values (%s, %s, %s, %s, %s)",
                      (user_id, b.starts_at, b.ends_at, b.all_day, b.title))
        busy = sum(b.busy for b in blocks)
        c.execute("update calendar_feeds set last_ok_at = %s, last_error = null, event_count = %s,"
                  " next_at = %s where user_id = %s", (now, busy, now + EVERY, user_id))
    return busy


def maybe_sync(user_id: str, now: datetime) -> bool:
    """Tick hook: syncs when calendar_feeds.next_at has passed (every 30 min, 2 h after errors)."""
    f = feed(user_id)
    if not f or f["next_at"] > now:
        return False
    try:
        sync(user_id, now)
        return True
    except CalendarError as e:
        log.info("calendar sync failed for %s: %s", user_id, e)
        return False
    except Exception:  # never let one person's feed stop the tick
        log.exception("calendar sync crashed for %s", user_id)
        return False


def sync_soon(user_id: str) -> None:
    """One sync in a background thread, right after setup (never inside a page render)."""
    def run():
        try:
            sync(user_id)
        except CalendarError:
            pass
        except Exception:
            log.exception("calendar sync crashed for %s", user_id)
    threading.Thread(target=run, daemon=True).start()
