from datetime import date

import httpx
import pytest

from app import intervals

CONN = intervals.Conn("i1", "secret-key-1234")


def fake(status, payload=None, calls=None):
    def _request(method, url, **kwargs):
        if calls is not None:
            calls.append(url)
        return httpx.Response(status, json=payload or {}, request=httpx.Request(method, url))
    return _request


def test_bad_key_gives_actionable_error(monkeypatch):
    monkeypatch.setattr(intervals.httpx, "request", fake(401))
    with pytest.raises(intervals.IntervalsError, match="refused the key"):
        intervals.get_athlete(CONN)


def test_retries_on_429(monkeypatch):
    calls = []
    monkeypatch.setattr(intervals.httpx, "request", fake(429, calls=calls))
    monkeypatch.setattr(intervals.time, "sleep", lambda s: None)
    with pytest.raises(intervals.IntervalsError):
        intervals.get_athlete(CONN)
    assert len(calls) == 3


def test_profile_from_athlete_fixture():
    athlete = {"name": "A B", "sex": "M", "icu_date_of_birth": "1995-05-01", "height": 1.82,
               "icu_weight": 74.3, "icu_resting_hr": 45, "timezone": "Europe/Kiev",
               "sportSettings": [
                   {"types": ["Run", "TrailRun"], "lthr": 185, "max_hr": 204,
                    "hr_zones": [123, 143, 164, 184, 204], "threshold_pace": 4.048583},
                   {"types": ["Swim"], "threshold_pace": 0.8333},
                   {"types": ["Other"]}]}
    p = intervals.profile_from_athlete(athlete)
    assert p["birth_year"] == 1995 and p["height_cm"] == 182 and p["time_zone"] == "Europe/Kyiv"
    assert p["sport_settings"]["Run"]["threshold_pace_per_km"] == "4:07"
    assert p["sport_settings"]["Swim"]["threshold_pace_per_100m"] == "2:00"
    assert "Other" not in p["sport_settings"]
    assert p["sport_settings"]["Run"]["hr_zones_bpm"] == {
        "Z1": "up to 123", "Z2": "124-143", "Z3": "144-164", "Z4": "165-184", "Z5": "185-204"}


def test_summarize_baselines():
    wellness = [{"id": "2026-11-13", "hrv": 70, "restingHR": 46, "sleepSecs": 7 * 3600},
                {"id": "2026-11-14", "hrv": 60, "restingHR": 50, "sleepSecs": 5 * 3600,
                 "ctl": 30, "atl": 40}]
    s = intervals.summarize(wellness, [], date(2026, 11, 14))
    assert s["today"]["sleep_h"] == 5.0 and s["today"]["form"] == -10
    assert s["baseline_7d"]["hrv"] == 70
