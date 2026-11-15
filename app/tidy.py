"""Duplicate items. Two layers:
1. `near_duplicate` (code): blocks saving an item that is almost the same as one already there
   ("Garmin Forerunner 965" vs "Garmin Forerunner 965 watch").
2. `find_groups` (LLM): groups items that mean the same thing in other words ("Garmin watch",
   "Forerunner 965"). The athlete sees each group and confirms before anything is merged."""

import re

from pydantic import BaseModel

from app import llm, store
from app.db import connection
from app.pipeline.common import to_json

STOP = {"the", "and", "with", "for", "from", "since", "have", "has", "uses", "use", "own",
        "owns", "athlete", "його", "для", "від", "має", "мій", "моя", "мої"}


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w']+", text.lower()) if len(w) >= 3 and w not in STOP}


def near_duplicate(text: str, items: list[dict]) -> dict | None:
    """An active item that says almost the same thing, or None."""
    a = tokens(text)
    if not a:
        return None
    for f in items:
        b = tokens(f["text"])
        if not b:
            continue
        overlap = len(a & b) / len(a | b)
        if overlap >= 0.6 or (len(a & b) >= 2 and (a <= b or b <= a)):
            return f
    return None


class Group(BaseModel):
    keep_id: int
    duplicate_ids: list[int]
    text: str
    why: str


class Groups(BaseModel):
    groups: list[Group]


PROMPT = """You get one athlete's saved items (id, category, text). Find items that describe
the SAME real thing (the same watch, the same shoes, the same injury, the same preference) in
different words. Different things must stay apart: two different shoe models are two items, a
watch and a heart-rate strap are two items. For each group: keep_id = the most complete item,
duplicate_ids = the others, text = one merged text with all useful details (model, dates, km),
in the language of the items, why = a short reason for a person (never mention ids).
Return no group when there are no duplicates."""


def find_groups(user_id: str) -> list[dict]:
    items = [f for f in store.list_facts(user_id)]
    if len(items) < 2:
        return []
    r = llm.complete(name="find-duplicate-items", schema=Groups, model=llm.SMART_MODEL,
                     user_id=user_id, max_tokens=1500, temperature=0, messages=[
                         {"role": "system", "content": PROMPT},
                         {"role": "user", "content": to_json([
                             {"id": f["id"], "category": f["category"], "text": f["text"]}
                             for f in items])}])
    by_id = {f["id"]: f for f in items}
    out = []
    for g in r.parsed.groups:
        dups = [i for i in g.duplicate_ids if i in by_id and i != g.keep_id]
        if g.keep_id in by_id and dups:
            out.append({"keep": by_id[g.keep_id], "dups": [by_id[i] for i in dups],
                        "text": g.text[:300], "why": g.why})
    return out


def merge(user_id: str, keep_id: int, dup_ids: list[int], text: str) -> None:
    store.update_fact(user_id, keep_id, text=text[:300])
    with connection() as c:
        for d in dup_ids:
            if d != keep_id:
                c.execute("delete from facts where user_id = %s and id = %s", (user_id, d))
