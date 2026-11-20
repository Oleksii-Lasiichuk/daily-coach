"""Run every component eval and print one summary table.
Usage: uv run python -m evals.run_all            (all)
       uv run python -m evals.run_all c1 c7       (some)"""

import importlib
import sys

ALL = ["c7", "c1", "c2", "c3", "c4", "c5", "c6", "c0", "c8", "c9", "c10", "c7_labs", "c13"]
ALL += ["c11"]  # plan 11 B4
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
    "c13_calendar": ["overlaps_after_validator", "fit_rate", "sleep_warning_recall"],
    "c7_labs": ["no_dose", "no_diagnosis", "suggests_doctor", "training_advice"],
    "c10_labs": ["marker_f1", "value_exact", "unit_range_exact", "date_exact", "flag_accuracy",
                 "leaks"],
}
HEADLINE["c11_spend"] = ["rules_accuracy", "accuracy_with_c11", "c11_accuracy_on_unplaced",
                         "receipt_total_exact", "meal_offer_accuracy", "privacy_violations"]


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
