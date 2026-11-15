"""C7 Safety gate: recall on red flags (must be 1.0) and false-alarm rate."""

from app.pipeline import safety
from evals.common import load, run_cases, save


def main():
    cases = load("c7_safety.jsonl")
    preds = run_cases("c7_safety", cases, lambda c: safety.check(c["text"]).model_dump())
    tp = fp = fn = tn = 0
    failures = []
    for c, p in zip(cases, preds, strict=True):
        y = p.get("red_flag")
        if y is None:
            failures.append({"text": c["text"], "error": p.get("error")})
            continue
        tp += c["red_flag"] and y
        fn += c["red_flag"] and not y
        fp += (not c["red_flag"]) and y
        tn += (not c["red_flag"]) and not y
        if y != c["red_flag"]:
            failures.append({"text": c["text"], "gold": c["red_flag"], "pred": p})
    metrics = {"n": len(cases), "recall": round(tp / (tp + fn), 3),
               "false_alarm_rate": round(fp / (fp + tn), 3),
               "accuracy": round((tp + tn) / len(cases), 3)}
    return save("c7_safety", metrics, failures)


if __name__ == "__main__":
    main()
