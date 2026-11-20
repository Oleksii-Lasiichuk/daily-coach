"""B2 ICS parsing (no network, no DB): recurring, all-day, time zones, limits."""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import calendar

ICS = Path(__file__).parent / "data" / "ics"
KYIV = ZoneInfo("Europe/Kyiv")


def _parse(name, start, end, titles=True):
    return calendar.parse((ICS / name).read_bytes(), KYIV, datetime(*start, tzinfo=KYIV),
                          datetime(*end, tzinfo=KYIV), keep_titles=titles)


def _local(b):
    return b.starts_at.astimezone(KYIV).strftime("%m-%d %H:%M")


def test_weekly_rrule_with_exdate_and_moved_occurrence():
    blocks = _parse("recurring.ics", (2026, 10, 19), (2026, 10, 26))
    assert [(_local(b), b.title) for b in blocks] == [
        ("10-19 09:30", "Standup"),            # Mon
        ("10-23 11:30", "Standup (moved)"),    # Fri moved by RECURRENCE-ID; Wed is EXDATE
    ]
    assert all(b.busy and not b.all_day for b in blocks)


def test_rrule_keeps_local_time_across_dst():
    # Kyiv leaves summer time on 25 Oct 2026: 18:00 local stays 18:00, UTC moves 15:00 -> 16:00
    blocks = _parse("timezones.ics", (2026, 10, 23), (2026, 10, 27))
    assert [_local(b) for b in blocks] == ["10-23 18:00", "10-24 18:00", "10-25 18:00",
                                           "10-26 18:00"]
    assert [b.starts_at.hour for b in blocks] == [15, 15, 16, 16]


def test_all_day_and_long_events_are_day_notes_not_busy():
    blocks = _parse("allday.ics", (2026, 11, 1), (2026, 11, 15))
    assert [(b.title, b.all_day, b.busy) for b in blocks] == [
        ("Holiday", True, False), ("Travel", True, False), ("Vacation", True, False)]
    holiday = blocks[0]  # DTEND is exclusive: one day, midnight to midnight local
    assert holiday.starts_at == datetime(2026, 11, 2, tzinfo=KYIV).astimezone(UTC)
    assert holiday.ends_at == datetime(2026, 11, 3, tzinfo=KYIV).astimezone(UTC)
    assert blocks[1].ends_at - blocks[1].starts_at == datetime(2026, 11, 7) - datetime(2026, 11, 4)


def test_utc_floating_cancelled_transparent():
    blocks = _parse("timezones.ics", (2026, 11, 10), (2026, 11, 12))
    assert [(_local(b), b.title) for b in blocks] == [
        ("11-10 14:00", "UTC meeting"),   # 12:00Z = 14:00 Kyiv (winter)
        ("11-11 08:00", "Floating"),      # floating time read in the person's zone
    ]  # cancelled and "show as free" are skipped


def test_window_end_is_exclusive():
    # the event starts exactly at the end of the window: not included; one minute later it is
    end = datetime(2026, 11, 15, tzinfo=UTC).astimezone(KYIV)
    ics = (ICS / "timezones.ics").read_bytes()
    start = datetime(2026, 11, 14, tzinfo=KYIV)
    assert "At the window end" not in [b.title for b in calendar.parse(ics, KYIV, start, end,
                                                                      True)]
    later = end.replace(minute=1)
    assert "At the window end" in [b.title for b in calendar.parse(ics, KYIV, start, later, True)]


def test_x_wr_timezone_moves_utc_series_to_the_calendar_zone():
    blocks = _parse("xwr.ics", (2026, 10, 19), (2026, 11, 3))
    assert [_local(b) for b in blocks] == ["10-19 10:00", "10-26 10:00", "11-02 10:00"]


def test_titles_dropped_unless_allowed():
    blocks = _parse("recurring.ics", (2026, 10, 19), (2026, 10, 26), titles=False)
    assert blocks and all(b.title is None for b in blocks)


def test_garbage_is_not_a_calendar():
    with pytest.raises(calendar.CalendarError):
        calendar.parse(b"BEGIN:VCALENDAR\r\nnot really\r\n", KYIV,
                       datetime(2026, 1, 1, tzinfo=KYIV), datetime(2026, 1, 2, tzinfo=KYIV))


def _client(body: bytes, status=200, ctype="text/calendar"):
    return httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(status, content=body, headers={"content-type": ctype})))


def test_fetch_webcal_becomes_https_and_reads_ics():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, content=(ICS / "xwr.ics").read_bytes())
    body = calendar.fetch("webcal://example.test/cal.ics",
                          httpx.Client(transport=httpx.MockTransport(handler)))
    assert body.startswith(b"BEGIN:VCALENDAR") and seen == ["https://example.test/cal.ics"]


def test_fetch_rejects_html_big_files_bad_links():
    with pytest.raises(calendar.CalendarError, match="isn't a calendar"):
        calendar.fetch("https://example.test/x", _client(b"<html>login</html>", ctype="text/html"))
    with pytest.raises(calendar.CalendarError, match="too big"):
        calendar.fetch("https://example.test/x",
                       _client(b"BEGIN:VCALENDAR\r\n" + b"X" * (5 * 1024 * 1024 + 10)))
    with pytest.raises(calendar.CalendarError, match="copy it again"):
        calendar.fetch("https://example.test/x", _client(b"", status=404))
    for bad in ("http://example.test/cal.ics", "ftp://x/y", "not a url", ""):
        with pytest.raises(calendar.CalendarError):
            calendar.normalize_url(bad)
