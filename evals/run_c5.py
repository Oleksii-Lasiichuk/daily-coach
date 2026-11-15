"""C5 Day type: accuracy and Cohen's kappa vs the athlete's label, against a code baseline that
only looks at device numbers (sleep + HRV)."""

from app.pipeline import daytype
from evals.common import cohen_kappa, load, run_cases, save

ORDER = ["recover", "easy", "normal", "push"]


def main():
    cases = load("c5_daytype.jsonl")
    preds = run_cases("c5_daytype", cases, lambda c: daytype.assess(c["inputs"]).model_dump())
    gold = [c["label"] for c in cases]
    pred = [p.get("day_type", "error") for p in preds]
    base = [daytype.rule_baseline(c["inputs"]) for c in cases]
    within_one = sum(abs(ORDER.index(g) - ORDER.index(p)) <= 1 for g, p in zip(gold, pred, strict=True)
                     if p in ORDER) / len(cases)
    confusion = {g: {p: 0 for p in ORDER + ["error"]} for g in ORDER}
    for g, p in zip(gold, pred, strict=True):
        confusion[g][p] += 1
    failures = [{"id": c["id"], "gold": g, "pred": p, "reasons": [r["evidence"] for r in pr.get("reasons", [])]}
                for c, g, p, pr in zip(cases, gold, pred, preds, strict=True) if g != p]
    metrics = {"n": len(cases),
               "accuracy": round(sum(g == p for g, p in zip(gold, pred, strict=True)) / len(cases), 3),
               "kappa": cohen_kappa(gold, pred), "within_one_level": round(within_one, 3),
               "baseline_accuracy": round(sum(g == b for g, b in zip(gold, base, strict=True)) / len(cases), 3),
               "baseline_kappa": cohen_kappa(gold, base)}
    return save("c5_daytype", metrics, failures, {"confusion": confusion})


if __name__ == "__main__":
    main()
