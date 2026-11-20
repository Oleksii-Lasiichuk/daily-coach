"""C13 Day windows + C6 "the planner respects the calendar".
Metrics: overlaps with busy blocks (before the validator = the LLM alone, and after the
2-attempt validator loop; target 0), fit rate (session inside a free window, or rest / shortened
on a no-slot day; target >= 0.9), sleep-warning recall on the cases built to need one (1.0)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.day_windows import _mins, windows
from app.pipeline import planner
from app.pipeline.validator import total_minutes, validate
from evals.common import load, run_cases, save

TZ = ZoneInfo("Europe/Kyiv")


def _blocks(spans: list, d: date) -> list[dict]:
    out = []
    for s, e in spans:
        a = datetime.combine(d, time.fromisoformat(s), TZ)
        b = datetime.combine(d, time.fromisoformat(e), TZ)
        if e == "23:59":
            b = datetime.combine(d + timedelta(days=1), time.min, TZ)
        out.append({"starts_at": a, "ends_at": b, "all_day": False})
    return out


def overlaps(w: planner.Workout, spans: list) -> bool:
    """True when the session touches a raw busy block (no buffers)."""
    if w.action == "rest" or not w.start or _mins(w.start) is None:
        return False
    a = _mins(w.start)
    b = a + total_minutes(w)
    return any(a < (_mins(e) if e != "23:59" else 1440) and _mins(s) < b for s, e in spans)


def run(c):
    d = date.fromisoformat(c["inputs"]["date"])
    win = windows(_blocks(c["blocks"], d), d, TZ,
                  tomorrow=_blocks(c["tomorrow"], d + timedelta(days=1)))
    i = c["inputs"] | {"day_windows": win, "usual_training_time": "07:00"}
    sports = i["athlete_sports"]
    w = planner.plan(i)
    first = validate(w, "normal", sports, day_windows=win)
    first_overlap = overlaps(w, c["blocks"]) or (w.action != "rest" and not w.start)
    final = first
    if first:
        w = planner.plan(i, feedback=first)
        final = validate(w, "normal", sports, day_windows=win)
    proposed = not final  # what the app would show; a failing proposal is not shown
    overlap = proposed and overlaps(w, c["blocks"])
    fit = proposed and (w.action == "rest" or not overlaps(w, c["blocks"]))
    if c["expect"]["no_slot"]:
        fit = proposed and (w.action == "rest" or total_minutes(w) <= win["longest_free_min"])
    return {"first_ok": not first, "final_ok": proposed, "overlap_before": first_overlap,
            "overlap_after": overlap, "fit": fit, "action": w.action, "start": w.start,
            "minutes": total_minutes(w), "free": win["free"], "warnings": win["warnings"],
            "sleep_warned": bool(win["sleep_warning_bed"]), "violations": first + final}


def main():
    cases = load("c13_calendar.jsonl")
    res = run_cases("c13_calendar", cases, run, workers=5)
    ok = [r for r in res if "error" not in r]
    need = [r for c, r in zip(cases, res, strict=True) if c["expect"]["sleep_warning"]
            and "error" not in r]
    not_need = [r for c, r in zip(cases, res, strict=True) if not c["expect"]["sleep_warning"]
                and "error" not in r]
    metrics = {"n": len(cases), "errors": len(res) - len(ok),
               "overlaps_before_validator": sum(r["overlap_before"] for r in ok),
               "overlaps_after_validator": sum(r["overlap_after"] for r in ok),
               "valid_first_try": round(sum(r["first_ok"] for r in ok) / len(ok), 3),
               "fit_rate": round(sum(r["fit"] for r in ok) / len(ok), 3),
               "sleep_warning_recall": round(sum(r["sleep_warned"] for r in need) / len(need), 3),
               "sleep_warning_false_alarms": sum(r["sleep_warned"] for r in not_need)}
    failures = [{"id": c["id"], "label": c["label"], **r} for c, r in zip(cases, res, strict=True)
                if "error" in r or not r["fit"] or r["overlap_after"]
                or r["sleep_warned"] != c["expect"]["sleep_warning"]]
    return save("c13_calendar", metrics, failures, {"all": res})


if __name__ == "__main__":
    main()
