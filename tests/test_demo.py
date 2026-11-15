"""Demo mode: /demo-login and the fake intervals.icu exist only in dev, only on localhost,
and only for the demo athlete id."""

from datetime import date

from app import demo, intervals
from app.config import get_settings


def test_demo_login_is_404_in_prod(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "prod")
    r = client.get("/demo-login", follow_redirects=False)
    assert r.status_code == 404


def test_demo_login_is_404_from_a_proxy(client):
    r = client.get("/demo-login", headers={"x-forwarded-host": "coach.example.com"},
                   follow_redirects=False)
    assert r.status_code == 404


def test_fake_intervals_only_for_the_demo_athlete(monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "dev")
    rows = intervals.get_wellness(intervals.Conn("demo", "x"), date(2026, 11, 1),
                                  date(2026, 11, 7))
    assert len(rows) == 7 and all("hrv" in r for r in rows)
    assert not demo.is_demo("i12345")
    monkeypatch.setattr(get_settings(), "env", "prod")
    assert not demo.is_demo("demo")  # in prod "demo" is just an unknown athlete id
