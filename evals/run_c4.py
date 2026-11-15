"""C4 Sources: ingest a synthetic ChatGPT export with 24 planted facts, then measure
- fact extraction: recall / precision / F1 of proposed facts vs the planted ones (judge-matched),
- retrieval: recall@5 and MRR — does the chunk holding the planted sentence come back for its
  question (UA/EN questions over a UA/EN file)?
Uses a temporary user that is deleted afterwards."""

import time
from statistics import mean

from pydantic import BaseModel

from app import llm, sources, store
from app.db import connection
from evals.common import DATA, judge, load, save


class Match(BaseModel):
    matched_gold_ids: list[str]
    extracted_matching_gold: int
    extracted_total: int


SYSTEM = """Match facts extracted by a system against gold facts about one person.
A gold fact is matched if some extracted fact states the same thing (wording and language may
differ; details like dates should agree). Return the ids of matched gold facts, how many
extracted facts match some gold fact, and the total number of extracted facts."""


def main():
    planted = load("c4_planted.jsonl")
    raw = (DATA / "c4_export.md").read_bytes()
    user = store.upsert_user("eval-c4", "eval-c4@test.invalid", "Eval C4")
    try:
        t = time.time()
        sid = sources.add_source(user.id, "c4_export.md", raw)
        src = {"status": "reading"}
        while src["status"] == "reading":
            src = sources.step(user.id, sid)
        ingest_s = time.time() - t
        if src["status"] == "error":
            raise RuntimeError(src["error"])
        extracted = [f["text"] for f in sources.proposed_facts(user.id)]
        m = judge("judge-fact-match", SYSTEM, {
            "gold": [{"id": p["id"], "fact": p["fact"]} for p in planted],
            "extracted": extracted}, Match)
        gold_hit = set(m.matched_gold_ids) & {p["id"] for p in planted}
        recall = len(gold_hit) / len(planted)
        # The judge can count one extracted fact against two gold facts; cap at 1.
        precision = min(1.0, m.extracted_matching_gold / max(1, len(extracted)))

        with connection() as c:
            chunks = c.execute("select idx, text from chunks where source_id = %s order by idx",
                               (sid,)).fetchall()
        ranks, failures = [], []
        for p in planted:
            gold_idx = {ch["idx"] for ch in chunks if p["sentence"] in ch["text"]}
            hits = sources.search(user.id, p["question"], k=5)
            rank = next((i + 1 for i, h in enumerate(hits)
                         if any(p["sentence"] in ch["text"] for ch in chunks
                                if ch["idx"] in gold_idx and ch["text"] == h["text"])), None)
            ranks.append(rank)
            if rank is None:
                failures.append({"id": p["id"], "question": p["question"],
                                 "top": [h["text"][:120] for h in hits[:2]]})
        missed = [p for p in planted if p["id"] not in gold_hit]
        failures += [{"id": p["id"], "missed_fact": p["fact"]} for p in missed]
        metrics = {
            "n_planted": len(planted), "n_chunks": len(chunks), "ingest_seconds": round(ingest_s),
            "facts_extracted": len(extracted), "fact_recall": round(recall, 3),
            "fact_precision": round(precision, 3),
            "fact_f1": round(2 * precision * recall / (precision + recall), 3)
            if precision + recall else 0.0,
            "retrieval_recall_at_5": round(mean(r is not None for r in ranks), 3),
            "retrieval_recall_at_1": round(mean(r == 1 for r in ranks), 3),
            "mrr": round(mean(1 / r if r else 0 for r in ranks), 3),
        }
        return save("c4_sources", metrics, failures, {"extracted": extracted})
    finally:
        llm.langfuse.flush()
        with connection() as c:
            c.execute("delete from users where id = %s", (user.id,))


if __name__ == "__main__":
    main()
