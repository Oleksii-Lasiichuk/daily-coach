"""C2 Log extractor: set-based P/R/F1 on (kind, day) and on kind only, plus field accuracy.

Set-based: "two coffees" as one or two drink events both count as one (drink, day) pair, so
the score measures what was detected and when, not how finely it was split."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.pipeline import extract
from evals.common import load, prf, run_cases, save


def predict(c):
    now = datetime.fromisoformat(c["now"]).replace(tzinfo=ZoneInfo("Europe/Kyiv"))
    return extract.extract(c["text"], now).model_dump(mode="json")


def main():
    cases = load("c2_extract.jsonl")
    preds = run_cases("c2_extract", cases, predict)
    kd, k = [0, 0, 0], [0, 0, 0]
    field_ok = field_n = 0
    day_ok = day_n = 0
    failures = []
    for c, p in zip(cases, preds, strict=True):
        events = p.get("events", [])
        gold_kd = {(e["kind"], e["day"]) for e in c["events"]}
        pred_kd = {(e["kind"], e["day"]) for e in events}
        gold_k, pred_k = {x[0] for x in gold_kd}, {x[0] for x in pred_kd}
        for acc, g, pr in ((kd, gold_kd, pred_kd), (k, gold_k, pred_k)):
            acc[0] += len(g & pr)
            acc[1] += len(pr - g)
            acc[2] += len(g - pr)
        # day accuracy among events whose kind was found
        for kind in gold_k & pred_k:
            day_n += 1
            day_ok += any((kind, d) in pred_kd for (gk, d) in gold_kd if gk == kind)
        # field checks where the gold has them
        for g in c["events"]:
            match = [e for e in events if e["kind"] == g["kind"]]
            if "sleep_hours" in g:
                field_n += 1
                field_ok += any(abs((e.get("sleep_hours") or -9) - g["sleep_hours"]) <= 0.25
                                for e in match)
            if "pain_location" in g:
                field_n += 1
                field_ok += any(g["pain_location"] in (e.get("pain_location") or "").lower()
                                for e in match)
            if "pain_score" in g:
                field_n += 1
                field_ok += any(e.get("pain_score") == g["pain_score"] for e in match)
            for key in ("distance_km", "duration_min"):
                if key in g:
                    field_n += 1
                    field_ok += any(abs((e.get(key) or -99) - g[key]) <= 0.05 * g[key]
                                    for e in match)
        if gold_kd != pred_kd:
            failures.append({"text": c["text"], "gold": sorted(gold_kd), "pred": sorted(pred_kd),
                             **({"error": p["error"]} if "error" in p else {})})
    metrics = {"n": len(cases), "kind_day_f1": prf(*kd)["f1"],
               "kind_day_precision": prf(*kd)["precision"], "kind_day_recall": prf(*kd)["recall"],
               "kind_f1": prf(*k)["f1"], "day_accuracy": round(day_ok / day_n, 3),
               "field_accuracy": round(field_ok / field_n, 3), "field_checks": field_n}
    return save("c2_extract", metrics, failures)


if __name__ == "__main__":
    main()
