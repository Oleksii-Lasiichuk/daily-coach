"""Code checks for a proposed workout (no LLM) and rendering to intervals.icu workout text."""

from app.pipeline.planner import Step, Workout

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
             injury_or_illness: bool = False) -> list[str]:
    """Returns rule violations (empty list = ok)."""
    if w.action == "rest":
        return []
    problems = []
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
    return problems


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


def to_intervals_text(w: Workout) -> str:
    """intervals.icu workout text, e.g. '- 10m Z1-Z2 HR', '5x', '- 400mtr Z4 Pace'."""
    parts = []
    for b in w.blocks:
        header = f"{b.name} {b.repeats}x" if b.repeats > 1 else b.name
        lines = [header] + [f"- {_amount(s)}{_target(s)}" for s in b.steps]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
