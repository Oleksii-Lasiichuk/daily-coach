"""C1 Tool routing (the coach agent's first step). The 60-message router set is re-scored as
"did the coach call the right tools":
  log → log_entries · plan → plan_sessions or assess_day · profile → save_item, update_profile
  or set_reminder · question/chitchat → no write tool.
Only the first model step is run; no tool is executed and nothing is written."""

from app import agent
from evals.common import load, prf, run_cases, save

GROUPS = {"log": {"log_entries"}, "plan": {"plan_sessions", "assess_day"},
          "profile": {"save_item", "update_profile", "set_reminder", "end_item"}}
CTX = {"now": "2026-11-14 Saturday 09:30 (Europe/Kyiv)", "profile": {}, "items": [],
       "today_logs": [], "past_days": []}


def main():
    cases = load("c1_router.jsonl")
    preds = run_cases("c1_router", cases, lambda c: {"tools": agent.first_tools(c["text"], CTX)})
    counts = {g: [0, 0, 0] for g in GROUPS}
    no_write_ok = no_write_n = exact = 0
    failures = []
    for c, p in zip(cases, preds, strict=True):
        tools = set(p.get("tools", []))
        gold = set(c["intents"])
        pred_groups = {g for g, ts in GROUPS.items() if tools & ts}
        gold_groups = gold & set(GROUPS)
        for g in GROUPS:
            counts[g][0] += g in gold_groups and g in pred_groups
            counts[g][1] += g not in gold_groups and g in pred_groups
            counts[g][2] += g in gold_groups and g not in pred_groups
        if not gold_groups:  # pure question / chitchat
            no_write_n += 1
            no_write_ok += not (tools & agent.WRITE_TOOLS)
        exact += pred_groups == gold_groups
        if pred_groups != gold_groups:
            failures.append({"text": c["text"], "gold": sorted(gold), "tools": sorted(tools),
                             **({"error": p["error"]} if "error" in p else {})})
    per = {g: prf(*counts[g]) for g in GROUPS}
    metrics = {"n": len(cases), "macro_f1": round(sum(v["f1"] for v in per.values()) / len(per), 3),
               "exact_match": round(exact / len(cases), 3),
               "no_write_on_questions": round(no_write_ok / max(1, no_write_n), 3),
               **{f"f1_{g}": per[g]["f1"] for g in GROUPS}}
    return save("c1_router", metrics, failures, {"per_group": per})


if __name__ == "__main__":
    main()
