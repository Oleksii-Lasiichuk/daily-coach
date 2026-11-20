"""C9 Day review: 15 synthetic days (evals/make_c9_days.py) → the coach's {good, short, tip}.

Checks:
- grounded (code): every number in the review is in the input, or a difference / percentage
  of a target and what was eaten (±2). Times like 08:00 count as input numbers.
- language (code): Ukrainian input → Cyrillic review, English → no Cyrillic.
- judge (Claude Haiku, another model family): `notices` = the review names what this day was
  designed to show (`expect`); `useful` 1–5; `false_claim` = says something the data contradicts.
Run: uv run python -m evals.run_c9
"""

import re
from statistics import mean

from pydantic import BaseModel

from app.pipeline import day_review
from evals.common import judge, load, run_cases, save

SYSTEM = """You check a nutrition coach's three-sentence review of one day against the day's data
and the analysis computed from it in code (its limits and statuses are part of the data;
"on target" means within 10% of the target). expected_point is the main thing a good review of
this day must notice.
notices: true if the review clearly makes the expected point (any wording, any language).
false_claim: true if any statement contradicts the data (wrong numbers, foods not eaten,
claims a target was met when it was not).
useful: 1-5, how useful and specific the review is for an athlete (5 = specific, correct,
actionable; 1 = generic or wrong).
Return JSON."""


class Check(BaseModel):
    notices: bool
    false_claim: bool
    useful: int
    comment: str


def allowed_numbers(inp: dict) -> set[float]:
    data = str(inp) + str(day_review.analyse(inp))
    nums = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", data)}
    for k, target in inp["targets"].items():
        eaten = inp["eaten"].get(k, 0)
        nums |= {abs(target - eaten), round(100 * eaten / target) if target else 0,
                 round(100 * abs(target - eaten) / target) if target else 0}
    if inp["eaten"].get("kcal") is not None:
        burned = sum(t.get("kcal") or 0 for t in inp["training"])
        nums |= {burned, abs(inp["targets"]["kcal"] - inp["eaten"]["kcal"])}
    return nums


def grounded(text: str, inp: dict) -> list[str]:
    ok = allowed_numbers(inp)
    bad = []
    for x in re.findall(r"\d+(?:[.,]\d+)?", text):
        v = float(x.replace(",", "."))
        if v <= 3:  # "one tip", "2 meals", "3 sentences": small counts are not data claims
            continue
        if not any(abs(v - a) <= 2 for a in ok):
            bad.append(x)
    return bad


def run(c):
    inp = c["input"]
    rv = day_review.review(inp)
    text = f"{rv.good} {rv.short} {rv.tip}"
    cyr = bool(re.search(r"[А-Яа-яЇїІіЄєҐґ]", text))
    g = judge("judge-day-review", SYSTEM, {"day": inp, "analysis": day_review.analyse(inp),
                                           "expected_point": c["expect"],
                                           "review": rv.model_dump()}, Check)
    return {"review": rv.model_dump(), "ungrounded_numbers": grounded(text, inp),
            "language_ok": cyr if inp["lang"] == "uk" else not cyr, **g.model_dump()}


def main():
    cases = load("c9_day_review.jsonl")
    res = run_cases("c9_day_review", cases, run)
    ok = [r for r in res if "error" not in r]
    metrics = {"n": len(cases), "errors": len(res) - len(ok),
               "grounded": round(mean(not r["ungrounded_numbers"] for r in ok), 3),
               "language_ok": round(mean(r["language_ok"] for r in ok), 3),
               "notices_expected": round(mean(r["notices"] for r in ok), 3),
               "no_false_claim": round(mean(not r["false_claim"] for r in ok), 3),
               "useful_mean_1_5": round(mean(r["useful"] for r in ok), 2)}
    failures = [{"id": c["id"], "expect": c["expect"], **r} for c, r in zip(cases, res, strict=True)
                if "error" in r or r["ungrounded_numbers"] or not r["language_ok"]
                or not r["notices"] or r["false_claim"]]
    return save("c9_day_review", metrics, failures, {"all": res})


if __name__ == "__main__":
    main()
