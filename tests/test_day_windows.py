"""C13 day windows (pure code)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.day_windows import fits, windows

TZ = ZoneInfo("Europe/Kyiv")
D = date(2026, 11, 18)


def b(start, end, day=D, all_day=False):
    h1, m1 = map(int, start.split(":"))
    h2, m2 = map(int, end.split(":"))
    return {"starts_at": datetime(day.year, day.month, day.day, h1, m1, tzinfo=TZ),
            "ends_at": datetime(day.year, day.month, day.day, h2, m2, tzinfo=TZ),
            "all_day": all_day}


def test_no_events_one_window_wake_to_bed():
    w = windows([], D, TZ)
    assert w["busy"] == [] and w["free"] == [["07:00", "22:30", 930]]
    assert w["warnings"] == [] and w["sleep_possible_h"] == 8.5


def test_back_to_back_events_merge_and_buffers():
    w = windows([b("10:00", "11:00"), b("11:00", "12:00"), b("14:00", "15:00")], D, TZ)
    assert w["busy"] == [["10:00", "12:00"], ["14:00", "15:00"]]
    # 60 min before the first event, 30 min around the others
    assert w["free"] == [["07:00", "09:00", 120], ["12:30", "13:30", 60],
                         ["15:30", "22:30", 420]]
    assert fits(w, "12:30", 60) and not fits(w, "12:30", 61) and not fits(w, "10:30", 20)


def test_buffers_that_touch_close_the_gap():
    w = windows([b("09:00", "12:00"), b("12:45", "14:00")], D, TZ)  # 45-min gap < 2 x 30
    assert [f[:2] for f in w["free"]] == [["07:00", "08:00"], ["14:30", "22:30"]]


def test_all_day_events_are_ignored():
    w = windows([b("00:00", "23:59", all_day=True)], D, TZ)
    assert w["free"] == [["07:00", "22:30", 930]]


def test_event_past_midnight_and_early_start_tomorrow_warn():
    late = {"starts_at": datetime(2026, 11, 18, 22, 0, tzinfo=TZ),
            "ends_at": datetime(2026, 11, 19, 0, 30, tzinfo=TZ), "all_day": False}
    flight = [b("07:00", "09:30", day=date(2026, 11, 19))]
    w = windows([late], D, TZ, tomorrow=flight)
    assert w["busy"] == [["22:00", "00:30"]]
    assert w["first_event_tomorrow"] == "07:00" and w["sleep_possible_h"] == 5.0
    assert w["bedtime_latest"] == "22:00" and len(w["warnings"]) == 1
    assert "00:30 event end" in w["warnings"][0] and "06:00 wake" in w["warnings"][0]


def test_early_first_event_moves_bedtime():
    w = windows([], D, TZ, tomorrow=[b("06:30", "07:30", day=date(2026, 11, 19))])
    assert w["bedtime_latest"] == "21:30" and w["sleep_possible_h"] == 7.0
    assert "aim to be in bed by 21:30" in w["warnings"][0]


def test_no_window_warning():
    w = windows([b("07:00", "12:00"), b("12:40", "17:00"), b("17:40", "22:30")], D, TZ)
    assert w["longest_free_min"] == 0 and any("No free window" in x for x in w["warnings"])
