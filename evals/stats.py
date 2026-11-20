"""95% Wilson intervals for the rate metrics in evals/results, and a majority-class baseline for
C5. Small sets give wide intervals; this script makes that visible instead of quoting 1.00.

Run: uv run python -m evals.stats   (reads results, writes evals/results/intervals.json)
"""

import json
from collections import Counter
from math import sqrt

from evals.common import RESULTS, load


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def metrics(name: str) -> dict:
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text())["metrics"] if path.exists() else {}


def majority_baseline_c5() -> dict:
    labels = [c["label"] for c in load("c5_daytype.jsonl")]
    top, k = Counter(labels).most_common(1)[0]
    return {"predicts": top, "accuracy": round(k / len(labels), 3), "kappa": 0.0}


def rows() -> list[dict]:
    m = {n: metrics(n) for n in ("c1_router", "c4_sources", "c5_daytype", "c6_planner",
                                 "c7_safety", "c8_reply", "c9_day_review", "injection",
                                 "e2e_agent")}
    out = []

    def add(component, metric, value, n):
        if value is None or not n:
            return
        k = round(value * n)
        lo, hi = wilson(k, n)
        out.append({"component": component, "metric": metric, "value": value, "k": k, "n": n,
                    "ci95": [lo, hi]})

    add("C7 safety", "recall (red flags found)", m["c7_safety"].get("recall"), 20)
    add("C7 safety", "false alarm rate", m["c7_safety"].get("false_alarm_rate"), 20)
    add("C1 tool routing", "exact match", m["c1_router"].get("exact_match"),
        m["c1_router"].get("n"))
    add("C4 search", "recall@5", m["c4_sources"].get("retrieval_recall_at_5"),
        m["c4_sources"].get("n_planted"))
    add("C4 search", "recall@1", m["c4_sources"].get("retrieval_recall_at_1"),
        m["c4_sources"].get("n_planted"))
    add("C5 day type", "accuracy", m["c5_daytype"].get("accuracy"), m["c5_daytype"].get("n"))
    add("C6 planner", "valid first try", m["c6_planner"].get("valid_first_try"),
        m["c6_planner"].get("n"))
    add("C8 answers", "correct", m["c8_reply"].get("correct"), m["c8_reply"].get("n"))
    add("C9 day review", "notices the main point", m["c9_day_review"].get("notices_expected"),
        m["c9_day_review"].get("n"))
    add("C9 day review", "no false claim", m["c9_day_review"].get("no_false_claim"),
        m["c9_day_review"].get("n"))
    add("Prompt injection", "attack success rate", m["injection"].get("attack_success_rate"),
        m["injection"].get("cases"))
    add("End-to-end agent", "case pass rate", m["e2e_agent"].get("case_pass_rate"),
        m["e2e_agent"].get("n"))
    return out


def main():
    table = rows()
    base = majority_baseline_c5()
    (RESULTS / "intervals.json").write_text(json.dumps(
        {"intervals": table, "c5_majority_baseline": base}, indent=1, ensure_ascii=False))
    print("| Component | Metric | Value | k/n | 95% CI |\n|---|---|---|---|---|")
    for r in table:
        print(f"| {r['component']} | {r['metric']} | {r['value']} | {r['k']}/{r['n']} | "
              f"{r['ci95'][0]:.2f}–{r['ci95'][1]:.2f} |")
    print(f"\nC5 majority-class baseline: always '{base['predicts']}', accuracy {base['accuracy']},"
          f" kappa {base['kappa']}")


if __name__ == "__main__":
    main()
