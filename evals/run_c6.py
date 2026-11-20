"""C6 Planner + validator: pass rate on the first try and after one retry with the violations,
plus an LLM-judge rubric (1-5) from a different model family."""

from statistics import mean

from pydantic import BaseModel, Field

from app.pipeline import planner
from app.pipeline.validator import to_intervals_text, total_minutes, validate
from evals.common import judge, load, run_cases, save

RUBRIC = """You grade a workout proposed by an AI coach for one athlete today.
Score 1-5 for each criterion (5 = excellent):
- safety_fit: matches the day type and health situation (intensity, duration, injuries, illness).
- plan_respect: keeps the athlete's own planned workout when it fits, changes it only with reason.
- specificity: concrete, executable steps with sensible warmup/cooldown and targets.
- rationale: the explanation cites the real evidence and is short and clear.
The reviewer note `expect` says what a good answer looks like; it is guidance, not the only answer.
Return JSON."""


class Grade(BaseModel):
    safety_fit: int = Field(ge=1, le=5)
    plan_respect: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5)
    rationale: int = Field(ge=1, le=5)
    comment: str


def run(c):
    i = c["inputs"]
    injury = any(f.startswith(("injury:", "health:")) for f in i["facts"])
    w = planner.plan(i)
    first = validate(w, i["day_type"], i["athlete_sports"], i["red_flag_today"], injury,
                     weather_flags=(i.get("weather") or {}).get("advice", {}).get("flags"))
    final = first
    if first:
        w = planner.plan(i, feedback=first)
        final = validate(w, i["day_type"], i["athlete_sports"], i["red_flag_today"], injury,
                     weather_flags=(i.get("weather") or {}).get("advice", {}).get("flags"))
    proposal = w.model_dump() | {"minutes": total_minutes(w), "text": to_intervals_text(w)}
    g = judge("judge-workout", RUBRIC, {"situation": i, "expect": c["expect"],
                                         "proposal": proposal}, Grade)
    return {"first_ok": not first, "final_ok": not final, "violations": first + final,
            "action": w.action, "sport": w.sport, "minutes": proposal["minutes"],
            "text": proposal["text"], "grade": g.model_dump()}


def main():
    cases = load("c6_planner.jsonl")
    res = run_cases("c6_planner", cases, run, workers=5)
    ok = [r for r in res if "error" not in r]
    crit = ["safety_fit", "plan_respect", "specificity", "rationale"]
    metrics = {"n": len(cases), "errors": len(res) - len(ok),
               "valid_first_try": round(mean(r["first_ok"] for r in ok), 3),
               "valid_after_retry": round(mean(r["final_ok"] for r in ok), 3),
               **{f"judge_{k}": round(mean(r["grade"][k] for r in ok), 2) for k in crit}}
    metrics["judge_mean"] = round(mean(metrics[f"judge_{k}"] for k in crit), 2)
    failures = [{"id": c["id"], "day_type": c["inputs"]["day_type"], "expect": c["expect"], **r}
                for c, r in zip(cases, res, strict=True)
                if "error" in r or not r["final_ok"] or min(r["grade"][k] for k in crit) <= 3]
    return save("c6_planner", metrics, failures, {"all": res})


if __name__ == "__main__":
    main()
