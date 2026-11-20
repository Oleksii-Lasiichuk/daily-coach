"""C10 Lab extraction on 15 synthetic sheets (evals/make_c10_labs.py): file → read_file →
model transcribes → code normalises. Compared with the labels row by row.

Metrics (overall and per kind: clean PNG, phone photo, text PDF):
- marker F1: catalogue markers by key, unknown markers by printed name
- value exact: value (±0.5 % or ±0.01) and qualifier, over matched rows
- unit + range exact: canonical unit, ref_low, ref_high, over matched catalogue rows
- date exact: taken_on (sheets carry a second, later "issued" date as a distractor)
- flag accuracy: low/high/in, over matched rows (end-to-end: shows the code part)
- leaks: the patient name or order number in any stored field
Run: uv run python -m evals.run_c10
"""

import time
from statistics import mean

from app import lab_catalog as cat
from app.pipeline import labs
from evals.common import DATA, load, prf, run_cases, save


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= max(0.01, 0.005 * abs(float(b)))


def row_key(r: dict) -> str:
    return r["marker"] or "?" + cat.key(r["name_as_printed"])


def run(c):
    t = time.time()
    raw = (DATA / "c10_labs" / c["file"]).read_bytes()
    content = labs.read_file(raw, c["file"])
    sheet = labs.extract(content)
    rows = labs.normalise(sheet)
    return {"lab": sheet.lab, "taken_on": str(labs.parse_date(sheet.taken_on)), "rows": rows,
            "seconds": round(time.time() - t, 1)}


def score(c, out) -> dict:
    gold = {row_key(g): g for g in c["rows"]}
    pred = {}
    for p in out["rows"]:
        pred.setdefault(row_key(p), p)
    matched = [k for k in pred if k in gold]
    value_ok = [k for k in matched if close(pred[k]["value"], gold[k]["value"])
                and pred[k]["qualifier"] == gold[k]["qualifier"]]
    known = [k for k in matched if gold[k]["marker"]]
    unit_ok = [k for k in known if pred[k]["unit"] == gold[k]["unit"]
               and close(pred[k]["ref_low"], gold[k]["ref_low"])
               and close(pred[k]["ref_high"], gold[k]["ref_high"])]
    flag_ok = [k for k in matched if pred[k]["flag"] == gold[k]["flag"]]
    stored = " ".join(str(v) for p in out["rows"] for v in p.values()) + " " + str(out["lab"])
    leaks = [x for x in (c["patient"], c["order"], c["patient"].split()[-1]) if x in stored]
    return {"tp": len(matched), "fp": len(pred) - len(matched), "fn": len(gold) - len(matched),
            "n_matched": len(matched), "value_ok": len(value_ok), "n_known": len(known),
            "unit_ok": len(unit_ok), "flag_ok": len(flag_ok),
            "date_ok": out["taken_on"] == c["taken_on"], "leaks": leaks,
            "missed": [k for k in gold if k not in pred], "extra": [k for k in pred
                                                                     if k not in gold],
            "wrong_value": [{"key": k, "pred": pred[k]["value"], "gold": gold[k]["value"]}
                            for k in matched if k not in value_ok],
            "wrong_unit_range": [{"key": k, "pred": [pred[k]["unit"], pred[k]["ref_low"],
                                                     pred[k]["ref_high"]],
                                  "gold": [gold[k]["unit"], gold[k]["ref_low"],
                                           gold[k]["ref_high"]]}
                                 for k in known if k not in unit_ok],
            "wrong_flag": [{"key": k, "pred": pred[k]["flag"], "gold": gold[k]["flag"]}
                           for k in matched if k not in flag_ok]}


def metrics(scores: list[dict]) -> dict:
    s = {k: sum(x[k] for x in scores) for k in ("tp", "fp", "fn", "n_matched", "value_ok",
                                                  "n_known", "unit_ok", "flag_ok")}
    return {"sheets": len(scores), "rows_gold": s["tp"] + s["fn"],
            "marker_f1": prf(s["tp"], s["fp"], s["fn"])["f1"],
            "value_exact": round(s["value_ok"] / max(s["n_matched"], 1), 3),
            "unit_range_exact": round(s["unit_ok"] / max(s["n_known"], 1), 3),
            "date_exact": f"{sum(x['date_ok'] for x in scores)}/{len(scores)}",
            "flag_accuracy": round(s["flag_ok"] / max(s["n_matched"], 1), 3),
            "leaks": sum(len(x["leaks"]) for x in scores)}


def main():
    cases = load("c10_labs.jsonl")
    res = run_cases("c10_labs", cases, run, workers=5)
    scored, failures = [], []
    for c, r in zip(cases, res, strict=True):
        if "error" in r:
            failures.append({"id": c["id"], "kind": c["kind"], "error": r["error"]})
            continue
        s = score(c, r) | {"id": c["id"], "kind": c["kind"], "lang": c["lang"]}
        scored.append(s)
        if (s["missed"] or s["extra"] or s["wrong_value"] or s["wrong_unit_range"]
                or s["wrong_flag"] or not s["date_ok"] or s["leaks"]):
            failures.append({k: v for k, v in s.items() if v not in ([], True)})
    m = metrics(scored) | {"n": len(cases), "errors": len(cases) - len(scored)}
    m["by_kind"] = {k: metrics([s for s in scored if s["kind"] == k])
                    for k in ("png", "photo", "pdf")}
    secs = [r["seconds"] for r in res if "seconds" in r]
    m["seconds_mean"], m["seconds_max"] = round(mean(secs), 1), round(max(secs), 1)
    return save("c10_labs", m, failures, {"mean_rows_per_sheet": round(mean(
        len(c["rows"]) for c in cases), 1)})


if __name__ == "__main__":
    main()
