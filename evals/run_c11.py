"""C11 Spend category: rules only vs rules + LLM on 161 synthetic payments, and receipt
extraction on 15 synthetic receipt images (evals/make_c11_spend.py).

Metrics:
- rules_accuracy (unplaced = wrong), rules_coverage, accuracy_with_c11, c11_accuracy_on_unplaced.
- privacy_violations: C11 inputs that contain anything but merchant + MCC, or a transfer row.
- receipt (first 10): total_exact, line_category_accuracy, split_ok (lines add up to the total
  that would match the card payment); meal_offer_accuracy on all 15.
Run: uv run python -m evals.run_c11
"""

import base64
import difflib
import json
from collections import Counter

from app import llm, spend_rules
from app.pipeline import receipt, spend
from evals.common import DATA, load, run_cases, save

PAIRS = [("eating_out", "delivery"), ("groceries", "sports_nutrition"),
         ("gym_classes", "race_entries"), ("coffee", "eating_out")]
_seen_inputs: list = []
_complete = llm.complete


def _spy(**kw):  # records what C11 sends, for the privacy check
    if kw.get("name") == "classify-spend":
        _seen_inputs.append(json.loads(kw["messages"][1]["content"]))
    return _complete(**kw)


def privacy_violations(transfer_names: set[str]) -> int:
    bad = 0
    for batch in _seen_inputs:
        for x in batch:
            if set(x) != {"merchant", "mcc"} or x["merchant"] in transfer_names:
                bad += 1
    return bad


def category_eval(rows: list[dict]) -> dict:
    rule = [spend_rules.categorise(r["description"], r["mcc"], r["amount_minor"]) for r in rows]
    left = [(spend_rules.normalise(r["description"]), r["mcc"]) for r, c in zip(rows, rule, strict=True)
            if c is None]
    llm.complete = _spy
    try:
        with llm.trace("eval-c11_spend", input={"n_merchants": len(left)}, user_id=None,
                       tags=["eval", "c11_spend"]) as root:
            got = spend.classify(left)
            root.update(output=got)
    finally:
        llm.complete = _complete
    final = [c or got.get(spend_rules.normalise(r["description"]), ("other", 0))[0]
             for r, c in zip(rows, rule, strict=True)]
    gold = [r["label"] for r in rows]
    unplaced = [i for i, c in enumerate(rule) if c is None]
    conf = Counter((g, p) for g, p in zip(gold, final, strict=True) if g != p)
    return {
        "n": len(rows),
        "rules_accuracy": round(sum(c == g for c, g in zip(rule, gold, strict=True)) / len(rows), 3),
        "rules_coverage": round(sum(c is not None for c in rule) / len(rows), 3),
        "accuracy_with_c11": round(sum(f == g for f, g in zip(final, gold, strict=True)) / len(rows), 3),
        "n_unplaced": len(unplaced),
        "c11_accuracy_on_unplaced": round(sum(final[i] == gold[i] for i in unplaced)
                                          / len(unplaced), 3) if unplaced else None,
        "privacy_violations": privacy_violations({r["description"] for r in rows
                                                  if r["label"] in ("transfers", "cash")}),
        "pair_confusions": {f"{a}/{b}": conf[(a, b)] + conf[(b, a)] for a, b in PAIRS},
    }, [{"id": r["id"], "description": r["description"], "mcc": r["mcc"], "gold": g,
         "rules": c, "final": f} for r, c, f, g in zip(rows, rule, final, gold, strict=True)
        if f != g or c is None]


def run_receipt(case):
    img = (DATA / case["image"]).read_bytes()
    rc = receipt.extract(img)
    lines = receipt.categorised_lines(rc)
    names = [ln["name"] for ln in case["lines"]]
    hits = 0
    for ln in case["lines"]:  # match each gold line to the closest extracted line
        best = max(lines, key=lambda x: difflib.SequenceMatcher(None, x["name"].lower(),
                                                                ln["name"].lower()).ratio(),
                   default=None)
        if best and best["category"] == ln["label"]:
            hits += 1
    return {"store": rc.store, "kind": rc.kind, "total": rc.total,
            "total_exact": abs(rc.total - case["total"]) < 0.01,
            "line_acc": hits / len(names),
            "split_ok": abs(sum(x["amount"] for x in lines) - case["total"]) <= 1,
            "offer": receipt.offer_for(rc, lines), "offer_ok": receipt.offer_for(rc, lines) == case["offer"],
            "lines": lines, "image_b64_len": len(base64.b64encode(img))}


def main():
    rows = load("c11_spend.jsonl")
    cat_metrics, cat_fail = category_eval(rows)
    recs = load("c11_receipts.jsonl")
    res = run_cases("c11_receipt", recs, run_receipt, workers=4)
    ok = [(c, r) for c, r in zip(recs, res, strict=True) if "error" not in r]
    acc = [(c, r) for c, r in ok if c["accuracy_set"]]
    metrics = {**cat_metrics,
               "receipts_n": len(recs), "receipt_errors": len(res) - len(ok),
               "receipt_total_exact": f"{sum(r['total_exact'] for _, r in acc)}/{len(acc)}",
               "receipt_line_accuracy": round(sum(r["line_acc"] for _, r in acc) / len(acc), 3)
               if acc else None,
               "receipt_split_ok": f"{sum(r['split_ok'] for _, r in acc)}/{len(acc)}",
               "meal_offer_accuracy": round(sum(r["offer_ok"] for _, r in ok) / len(ok), 3)
               if ok else None}
    rec_fail = [{"id": c["id"], "expected_total": c["total"], "expected_offer": c["offer"], **r}
                for c, r in zip(recs, res, strict=True)
                if "error" in r or not r["total_exact"] or r["line_acc"] < 1 or not r["offer_ok"]]
    return save("c11_spend", metrics, cat_fail + rec_fail, {"c11_inputs": _seen_inputs})


if __name__ == "__main__":
    main()
