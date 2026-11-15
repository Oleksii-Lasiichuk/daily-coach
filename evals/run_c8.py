"""C8 Reply: the coach agent answers 15 questions over a fixed athlete context (no tools).
Judge: correct and grounded; for questions whose answer is not in the context, the reply must
say it is missing."""

import json
from statistics import mean

from pydantic import BaseModel

from app import agent
from evals.common import DATA, judge, load, run_cases, save

CONTEXT = json.loads((DATA / "c8_context.json").read_text())
SYSTEM = """You check a coach's chat reply against the athlete context and a reference answer.
correct: the reply answers the question correctly (for 'missing' questions: it clearly says the
information is not available instead of inventing it).
grounded: every fact about the athlete in the reply is supported by the context.
Return JSON."""


class Check(BaseModel):
    correct: bool
    grounded: bool
    comment: str


def run(c):
    text = agent.answer_only(c["question"], CONTEXT)
    g = judge("judge-reply", SYSTEM, {"context": CONTEXT, "question": c["question"],
                                      "reference": c["expected"], "type": c["type"],
                                      "reply": text}, Check)
    return {"reply": text, **g.model_dump()}


def main():
    cases = load("c8_reply.jsonl")
    res = run_cases("c8_reply", cases, run)
    ok = [r for r in res if "error" not in r]
    miss = [r for c, r in zip(cases, res, strict=True) if c["type"] == "missing" and "error" not in r]
    metrics = {"n": len(cases), "errors": len(res) - len(ok),
               "correct": round(mean(r["correct"] for r in ok), 3),
               "grounded": round(mean(r["grounded"] for r in ok), 3),
               "says_missing": round(mean(r["correct"] for r in miss), 3) if miss else None}
    failures = [{"question": c["question"], **r} for c, r in zip(cases, res, strict=True)
                if "error" in r or not (r["correct"] and r["grounded"])]
    return save("c8_reply", metrics, failures, {"all": res})


if __name__ == "__main__":
    main()
