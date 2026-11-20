"""Code checks for a proposed workout (no LLM) and rendering to intervals.icu workout text."""

import re

from app.pipeline.planner import Step, Workout

OUTDOOR = {"Run", "TrailRun", "Ride", "MountainBikeRide", "GravelRide", "Walk", "Hike",
           "Rowing", "Ski"}  # B1: sports usually done outside
LIMITS = {"recover": (40, 2), "easy": (75, 2), "normal": (180, 5), "push": (180, 5)}


def total_minutes(w: Workout, pace_min_per_km: float = 6.0) -> float:
    """Distance steps are converted with a rough pace so the duration rule still applies."""
    total = 0.0
    for b in w.blocks:
        block = 0.0
        for s in b.steps:
            if s.duration_min:
                block += s.duration_min
            elif s.distance_m:
                per_km = 25.0 if w.sport.lower().startswith("swim") else pace_min_per_km
                block += s.distance_m / 1000 * per_km
        total += block * b.repeats
    return round(total, 1)


def max_zone(w: Workout) -> int:
    zones = [s.zone_high or s.zone_low or 0 for b in w.blocks for s in b.steps]
    return max(zones, default=0)


def validate(w: Workout, day_type: str, sports: list[str], red_flag: bool = False,
             injury_or_illness: bool = False, day_windows: dict | None = None,
             weather_flags: list[str] | None = None) -> list[str]:
    """Returns rule violations (empty list = ok). day_windows: C13 output when the day has
    calendar data; then the session must start inside one free window and end before it closes."""
    if w.action == "rest":
        return []
    problems = calendar_problems(w, day_windows) if day_windows else []
    if red_flag:
        problems.append("A red flag was raised today: only 'rest' is allowed.")
    if sports and w.sport not in sports:
        problems.append(
            f"Sport '{w.sport}' is not one of the athlete's sports: {', '.join(sports)}.")
    if not w.blocks or not any(b.steps for b in w.blocks):
        problems.append("The workout has no steps.")
    elif not any(s.kind in ("work", "steady") for b in w.blocks for s in b.steps):
        problems.append("There is no main set: add the work or steady part of the session, "
                        "not only warmup/cooldown.")
    for b in w.blocks:
        for s in b.steps:
            if not s.duration_min and not s.distance_m:
                problems.append(f"A step in '{b.name}' has neither duration nor distance.")
            if s.zone_low and s.zone_high and s.zone_low > s.zone_high:
                problems.append(f"A step in '{b.name}' has zone_low above zone_high.")
            if s.target != "none" and not (s.zone_low or s.zone_high):
                problems.append(f"A step in '{b.name}' has a {s.target} target but no zone.")
    minutes = total_minutes(w)
    if not 10 <= minutes <= 180:
        problems.append(f"Total duration {minutes} min is outside 10–180 min.")
    max_min, max_z = LIMITS[day_type]
    if minutes > max_min:
        problems.append(f"A {day_type} day allows at most {max_min} min (got {minutes}).")
    if max_zone(w) > max_z:
        problems.append(f"A {day_type} day allows zones up to {max_z} (got zone {max_zone(w)}).")
    if injury_or_illness and max_zone(w) > 2:
        problems.append("An active injury or illness allows zones up to 2 only.")
    bad_out = [f for f in ("indoors_aqi", "storm") if f in (weather_flags or [])]
    if bad_out and w.sport in OUTDOOR and max_zone(w) >= 4:
        problems.append(f"weather.advice.flags has {', '.join(bad_out)}: no zone 4+ outdoors. "
                        "Either switch to an indoor sport from athlete_sports (e.g. "
                        "WeightTraining) or keep every step in zone 1–3, and say why.")
    return problems


def calendar_problems(w: Workout, day_windows: dict) -> list[str]:
    """B2: the hard guarantee that a session never sits on top of a busy block."""
    from app.day_windows import fits
    minutes = total_minutes(w)
    free = ", ".join(f"{a}–{b} ({m} min)" for a, b, m in day_windows["free"]) or "none"
    if not w.start:
        return [f"The day has calendar data: set `start` (HH:MM) inside a free window ({free})."]
    if not fits(day_windows, w.start, minutes):
        longest = day_windows["longest_free_min"]
        return [f"Start {w.start} + {minutes:g} min does not fit inside one free window "
                f"({free}). Move it into a window, shorten it to the longest window "
                f"({longest} min), or rest and say which day to move it to."]
    return []


def _amount(s: Step) -> str:
    if s.duration_min:
        m = s.duration_min
        return f"{int(m)}m" if m == int(m) else f"{int(round(m * 60))}s"
    return f"{s.distance_m}mtr"


def _target(s: Step) -> str:
    if s.target == "none" or not (s.zone_low or s.zone_high):
        return ""
    lo, hi = s.zone_low or s.zone_high, s.zone_high or s.zone_low
    zone = f"Z{lo}" if lo == hi else f"Z{lo}-Z{hi}"
    return f" {zone} {s.target}"


def watch_cue(cue: str) -> str:
    """The step text the watch shows. Numbers are removed so intervals.icu can't read them as a
    duration or target ('strides 4×20 s' would otherwise become a 20 s step)."""
    text = re.sub(r"\d+\s*[x×]\s*\d+", " ", cue or "")
    text = re.sub(r"[0-9×%:/.,()\-]+", " ", text)
    text = re.sub(r"\b(min|sec|s|m|km|bpm|reps?|sets?|Z)\b", " ", text, flags=re.I)
    text = " ".join(text.split())
    return text if len(text) <= 40 else text[:41].rsplit(" ", 1)[0]


def to_intervals_text(w: Workout) -> str:
    """intervals.icu workout text, e.g. '- Easy jog 10m Z1-Z2 HR', '5x', '- 400mtr Z4 Pace'.
    Text before the duration is the step's cue on the watch."""
    parts = []
    for b in w.blocks:
        header = f"{b.name} {b.repeats}x" if b.repeats > 1 else b.name
        lines = [header] + [f"- {(watch_cue(s.cue) + ' ') if watch_cue(s.cue) else ''}"
                            f"{_amount(s)}{_target(s)}" for s in b.steps]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
