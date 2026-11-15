"""Shared eval helpers: data loading, parallel runs (each case is one Langfuse trace tagged
`eval`), an LLM judge from a different model family, metrics, result files."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", "eval")

from app import llm  # noqa: E402

ROOT = Path(__file__).parent
DATA, RESULTS = ROOT / "data", ROOT / "results"
JUDGE_MODEL = "anthropic/claude-haiku-5.5"  # not Gemini: avoids a model grading its own family


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in open(DATA / name) if line.strip()]


def run_cases(component: str, cases: list, fn, workers: int = 6) -> list:
    """fn(case) -> result dict. Exceptions become {"error": ...} so one failure never stops a run."""

    def one(case):
        with llm.trace(f"eval-{component}", input=case, user_id=None, tags=["eval", component]) as root:
            try:
                out = fn(case)
            except Exception as e:  # recorded as a failed case
                out = {"error": f"{type(e).__name__}: {e}"}
            root.update(output=out)
            return out

    t = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, cases))  # each case starts its own trace
    llm.langfuse.flush()
    print(f"{component}: {len(cases)} cases in {time.time() - t:.0f}s")
    return results


def judge(name: str, system: str, payload: dict, schema):
    r = llm.complete(name=name, model=JUDGE_MODEL, schema=schema, max_tokens=600, temperature=0,
                     messages=[{"role": "system", "content": system},
                               {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
    return r.parsed


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3)}


def cohen_kappa(gold: list, pred: list) -> float:
    labels = sorted(set(gold) | set(pred))
    n = len(gold)
    po = sum(g == p for g, p in zip(gold, pred, strict=True)) / n
    pe = sum((gold.count(lab) / n) * (pred.count(lab) / n) for lab in labels)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def save(component: str, metrics: dict, failures: list, extra: dict | None = None) -> dict:
    RESULTS.mkdir(exist_ok=True)
    out = {"component": component, "metrics": metrics, "n_failures": len(failures),
           "failures": failures, **(extra or {})}
    (RESULTS / f"{component}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1,
                                                          default=str))
    print(json.dumps(metrics, ensure_ascii=False))
    return out
