"""C12 Weather advice eval: the hand-written rule-case table evals/data/c12_weather.jsonl
(also run by tests/test_weather_rules.py). Pure code, no LLM. Metric: pass rate per rule family.
Usage: uv run python -m evals.run_c12"""

import json
from pathlib import Path

from app import weather_rules as r

DATA = Path(__file__).parent / "data" / "c12_weather.jsonl"
# A mild, dry, calm hour; each case overrides only what it tests.
BASE_HOUR = {"temperature_2m": 10, "apparent_temperature": 10, "dew_point_2m": 5,
             "precipitation": 0, "precipitation_probability": 0, "weather_code": 1,
             "wind_gusts_10m": 10, "uv_index": 1, "european_aqi": 20}


def cases() -> list[dict]:
    return [json.loads(line) for line in open(DATA) if line.strip()]


def _hours(rows: list[dict] | None) -> list[dict]:
    return [BASE_HOUR | h for h in rows or []]


def actual(case: dict):
    """What the rules return for one case, in the shape of case["expect"]."""
    i = case["input"]
    fn = case["fn"]
    if fn == "heat_sum":
        return r.heat_sum_f(i["temp_c"], i["dew_c"])
    if fn == "pace":
        band, level = r.pace_band(i["sum_f"])
        return {"band": band, "level": level}
    if fn == "clothing":
        return r.clothing(i.get("feels"), i.get("gusts"), i.get("rain_prob"), i.get("uv"))
    if fn == "flags":
        return r.flags(_hours(i["hours"]), i.get("start"), i.get("minutes", 60),
                       i.get("sunrise"), i.get("sunset"), _hours(i.get("before")),
                       i.get("allergic", False))
    if fn == "best_hour":
        day = {k: BASE_HOUR | v for k, v in i["day_hours"].items()}
        return r.best_hour(day, i.get("minutes", 60), i.get("sunrise"), i.get("sunset"))
    if fn == "advise":
        out = r.advise(_hours(i["hours"]) if i["hours"] is not None else [],
                       i.get("sport", "Run"), i.get("start"), i.get("minutes", 60),
                       i.get("sunrise"), i.get("sunset"))
        return {k: out.get(k) for k in case["expect"]}
    raise ValueError(f"unknown fn {fn}")


def main() -> dict:
    from evals.common import save
    by_family: dict[str, list[bool]] = {}
    failures = []
    for c in cases():
        got = actual(c)
        ok = got == c["expect"]
        by_family.setdefault(c["family"], []).append(ok)
        if not ok:
            failures.append({"id": c["id"], "expect": c["expect"], "got": got})
    n = sum(len(v) for v in by_family.values())
    metrics = {"n": n, "pass_rate": round(sum(sum(v) for v in by_family.values()) / n, 3),
               **{f"pass_{k}": round(sum(v) / len(v), 3) for k, v in sorted(by_family.items())}}
    return save("c12_weather", metrics, failures)


if __name__ == "__main__":
    main()
