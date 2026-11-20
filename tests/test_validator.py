from app.pipeline.planner import Block, Step, Workout
from app.pipeline.validator import to_intervals_text, total_minutes, validate


def run(minutes, zone, action="modify", sport="Run"):
    return Workout(action=action, sport=sport, name="x", rationale="r", evidence=[], blocks=[
        Block(name="Main", steps=[Step(kind="steady", duration_min=minutes, target="HR",
                                       zone_low=1, zone_high=zone)])])


def test_recover_day_limits():
    assert validate(run(35, 2), "recover", ["Run"]) == []
    assert any("at most 40" in p for p in validate(run(50, 2), "recover", ["Run"]))
    assert any("zones up to 2" in p for p in validate(run(30, 4), "recover", ["Run"]))


def test_injury_and_red_flag_and_sport():
    assert any("injury" in p for p in validate(run(30, 3), "normal", ["Run"],
                                               injury_or_illness=True))
    assert any("red flag" in p for p in validate(run(30, 1), "normal", ["Run"], red_flag=True))
    assert any("not one of" in p for p in validate(run(30, 2), "normal", ["Swim"]))
    assert validate(run(0, 1, action="rest"), "recover", ["Run"], red_flag=True) == []


def test_warmup_only_is_rejected():
    w = Workout(action="add", sport="Run", name="50 min threshold", rationale="r", evidence=[],
                blocks=[Block(name="Warmup", steps=[Step(kind="warmup", duration_min=15,
                                                         zone_low=1, zone_high=2)])])
    assert any("no main set" in p for p in validate(w, "normal", ["Run"]))


def test_text_and_minutes():
    w = Workout(action="add", sport="Run", name="x", rationale="r", evidence=[], blocks=[
        Block(name="Warmup", steps=[Step(kind="warmup", duration_min=10, zone_low=1, zone_high=2)]),
        Block(name="Main set", repeats=5, steps=[
            Step(kind="work", distance_m=400, target="Pace", zone_low=4, zone_high=4),
            Step(kind="recovery", duration_min=1.5, target="none")])])
    assert to_intervals_text(w) == ("Warmup\n- 10m Z1-Z2 HR\n\nMain set 5x\n"
                                    "- 400mtr Z4 Pace\n- 90s")
    assert total_minutes(w) == 10 + 5 * (0.4 * 6 + 1.5)


def test_calendar_start_must_fit_a_free_window():
    w = {"free": [["07:00", "09:00", 120], ["12:30", "13:30", 60]], "longest_free_min": 120}
    session = run(45, 2)
    assert any("set `start`" in p for p in validate(session, "normal", ["Run"], day_windows=w))
    session.start = "12:50"  # 12:50 + 45 min ends 13:35, past the 13:30 window end
    assert any("does not fit" in p for p in validate(session, "normal", ["Run"], day_windows=w))
    session.start = "07:15"
    assert validate(session, "normal", ["Run"], day_windows=w) == []
    assert validate(session, "normal", ["Run"]) == []  # no calendar: no start needed
