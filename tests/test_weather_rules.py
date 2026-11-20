"""C12 rule tables: every case of evals/data/c12_weather.jsonl (same table as evals/run_c12.py)."""

import pytest

from app import weather_rules as r
from evals.run_c12 import BASE_HOUR, actual, cases


@pytest.mark.parametrize("case", cases(), ids=lambda c: c["id"])
def test_case(case):
    assert actual(case) == case["expect"]


def test_ride_gets_drink_fact_not_pace():
    out = r.advise([BASE_HOUR | {"temperature_2m": 30, "dew_point_2m": 20}], sport="Ride")
    assert any("drink more" in f for f in out["facts"])
    assert not any("pace" in f for f in out["facts"])


def test_best_hour_fact_only_when_flagged():
    day = {"07:00": BASE_HOUR, "18:00": BASE_HOUR | {"european_aqi": 95}}
    out = r.advise([day["18:00"]], start="18:00", sunrise="06:00", sunset="20:00", day_hours=day)
    assert out["flags"] == ["indoors_aqi"] and out["best_hour"] == "07:00"
    assert "Better time today: 07:00." in out["facts"]


def test_validator_blocks_hard_outdoor_work_on_bad_air():
    from app.pipeline.planner import Block, Step, Workout
    from app.pipeline.validator import validate
    w = Workout(action="modify", sport="Run", name="Intervals", rationale="", evidence=[],
                blocks=[Block(name="main", repeats=5, steps=[Step(kind="work", duration_min=3,
                                                                  zone_low=4, zone_high=4)])])
    assert any("indoors_aqi" in p for p in validate(w, "push", ["Run"],
                                                    weather_flags=["indoors_aqi"]))
    assert not validate(w, "push", ["Run"], weather_flags=[])
    assert not validate(w.model_copy(update={"sport": "WeightTraining"}), "push",
                        ["WeightTraining"], weather_flags=["indoors_aqi"])


def test_session_handles_missing_forecast(monkeypatch):
    from datetime import date

    from app import weather
    monkeypatch.setattr(weather, "forecast", lambda *a: {})
    assert weather.session(None, date(2026, 11, 21)) is None
    assert weather.session({"name": "X", "lat": 1, "lon": 1}, date(2026, 11, 21))["error"]
