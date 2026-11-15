"""C3 Nutrition: MAE of kcal / carbs / protein / fat vs NutriBench (public, CC BY-NC-SA 4.0)
and 10 Ukrainian meals with reference-table gold. Baseline: always predict the set mean."""

from statistics import mean

from app.pipeline import nutrition
from evals.common import load, run_cases, save

KEYS = ["kcal", "carbs_g", "protein_g", "fat_g"]


def mae(rows, key, pred_key=None):
    return round(mean(abs(r["pred"][key] - r["gold"][key]) for r in rows), 1)


def main():
    cases = load("c3_nutrition.jsonl")
    preds = run_cases("c3_nutrition", cases,
                      lambda c: nutrition.estimate(c["text"]).model_dump(exclude={"totals"}))
    rows, failures = [], []
    for c, p in zip(cases, preds, strict=True):
        if "error" in p:
            failures.append({"text": c["text"], "error": p["error"]})
            continue
        rows.append({"source": c["source"], "gold": {k: c[k] for k in KEYS},
                     "pred": {k: p[k] for k in KEYS}, "text": c["text"]})
    metrics = {"n": len(cases), "errors": len(failures)}
    for source in ("nutribench-v2", "ua-reference-table"):
        sub = [r for r in rows if r["source"] == source]
        tag = "nb" if source.startswith("nutri") else "ua"
        for k in KEYS:
            metrics[f"{tag}_mae_{k}"] = mae(sub, k)
            m = mean(r["gold"][k] for r in sub)
            metrics[f"{tag}_baseline_mae_{k}"] = round(mean(abs(r["gold"][k] - m) for r in sub), 1)
        metrics[f"{tag}_within_20pct_kcal"] = round(mean(
            abs(r["pred"]["kcal"] - r["gold"]["kcal"]) <= 0.2 * r["gold"]["kcal"] for r in sub), 3)
    worst = sorted(rows, key=lambda r: -abs(r["pred"]["kcal"] - r["gold"]["kcal"]))[:8]
    failures += [{"text": r["text"], "gold_kcal": r["gold"]["kcal"], "pred_kcal": r["pred"]["kcal"]}
                 for r in worst]
    return save("c3_nutrition", metrics, failures)


if __name__ == "__main__":
    main()
