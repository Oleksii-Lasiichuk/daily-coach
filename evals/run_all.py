"""Run every component eval and print one summary table.
Usage: uv run python -m evals.run_all            (all)
       uv run python -m evals.run_all c1 c7       (some)"""

import importlib
import sys

ALL = ["c7", "c1", "c2", "c3", "c4", "c5", "c6", "c0", "c8", "c9", "c12"]
HEADLINE = {
    "c7_safety": ["recall", "false_alarm_rate"],
    "c1_router": ["macro_f1", "exact_match", "no_write_on_questions"],
    "c2_extract": ["kind_day_f1", "day_accuracy", "field_accuracy"],
    "c3_nutrition": ["nb_mae_kcal", "nb_baseline_mae_kcal", "ua_mae_kcal", "ua_baseline_mae_kcal"],
    "c4_sources": ["fact_recall", "fact_precision", "retrieval_recall_at_5", "mrr"],
    "c5_daytype": ["accuracy", "kappa", "baseline_kappa"],
    "c6_planner": ["valid_first_try", "valid_after_retry", "judge_mean"],
    "c0_interview": ["slot_coverage", "slot_accuracy", "redundant_questions"],
    "c8_reply": ["correct", "grounded", "says_missing"],
    "c9_day_review": ["grounded", "notices_expected", "no_false_claim", "useful_mean_1_5"],
    "c12_weather": ["pass_rate", "pass_heat", "pass_clothing", "pass_flags", "pass_best_hour"],
}


def main(selected: list[str]):
    rows = []
    for c in selected:
        out = importlib.import_module(f"evals.run_{c}").main()
        m = out["metrics"]
        rows.append((out["component"], m.get("n", m.get("n_planted")),
                     ", ".join(f"{k}={m[k]}" for k in HEADLINE[out["component"]])))
    print("\n| Component | n | Headline metrics |\n|---|---|---|")
    for name, n, text in rows:
        print(f"| {name} | {n} | {text} |")


if __name__ == "__main__":
    main(sys.argv[1:] or ALL)
