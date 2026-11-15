"""Sample watch data: the simulated intervals.icu answers only for the athlete id "demo"."""

from datetime import date

from app import demo, intervals
from app.config import get_settings


def test_fake_intervals_only_for_the_demo_athlete(monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "prod")  # sample data works in prod too
    rows = intervals.get_wellness(intervals.Conn("demo", "x"), date(2026, 11, 1),
                                  date(2026, 11, 7))
    assert len(rows) == 7 and all("hrv" in r for r in rows)
    assert demo.is_demo("demo") and not demo.is_demo("i12345")
