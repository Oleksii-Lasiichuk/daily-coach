"""C9 Day review: the coach's three-sentence review of one day's eating (Nutrition page).

Input: that day's totals, targets for its day type, meals with times, drinks, training (all
computed in code). Output: DayReview {good, short, tip} in the user's language. Cached per day
and language until the day's numbers change (table day_reviews).
"""

import hashlib
import json

from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app import llm
from app.db import connection
from app.pipeline.common import prompt, to_json


class DayReview(BaseModel):
    good: str
    short: str
    tip: str


LIMITS = {"caffeine_mg": 400, "alcohol_g": 20}
WATER_L = 1.5
MACROS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g")


def analyse(day: dict) -> dict:
    """The comparisons, in code: status per target and the day's issues, worst first. The
    model only puts these into words (it compares numbers badly)."""
    t, e = day["targets"], day["eaten"]
    status, issues, good = {}, [], []
    for k in MACROS + ("sugar_g", "salt_g"):
        tgt, val = t.get(k), e.get(k, 0)
        if not tgt:
            continue
        pct = round(100 * val / tgt)
        limit = k in ("sugar_g", "salt_g")
        state = ("over the limit" if val > tgt else "within the limit") if limit else (
            "on target" if 90 <= pct <= 110 else "under" if pct < 90 else "over")
        status[k] = {"eaten": val, "target": tgt, "difference": val - tgt, "percent": pct,
                     "status": state}
        if state in ("on target", "within the limit"):
            good.append(k)
    open_day = not day.get("day_is_over", True)
    hard = day.get("day_type") == "push" or any((x.get("minutes") or 0) >= 75
                                                for x in day.get("training", []))

    def add(score: float, text: str):
        issues.append((score, text))

    d = day.get("drinks", {})
    if d.get("alcohol_g", 0) > LIMITS["alcohol_g"]:
        add(3 + d["alcohol_g"] / 20, f"alcohol {d['alcohol_g']} g (limit 20 g)"
            + (" on a recovery day" if day.get("day_type") == "recover" else ""))
    if d.get("caffeine_mg", 0) > LIMITS["caffeine_mg"]:
        add(2 + d["caffeine_mg"] / 400, f"caffeine {d['caffeine_mg']} mg (limit 400 mg)")
    for k, s in status.items():
        if s["status"] == "over the limit":
            add(1 + s["percent"] / 100, f"{k} {s['eaten']} over the limit {s['target']}")
        elif s["status"] == "under" and not open_day:
            weight = 2.5 if (k == "carbs_g" and hard) or k == "protein_g" else 1.5
            add(weight * (100 - s["percent"]) / 30, f"{k} {s['eaten']} of {s['target']} "
                f"({-s['difference']} under)")
        elif s["status"] == "over" and k in ("kcal", "fat_g") and s["percent"] > 115:
            add((s["percent"] - 100) / 15, f"{k} {s['eaten']} of {s['target']} "
                f"({s['difference']} over)")
    if d.get("water_l") is not None and d["water_l"] < WATER_L and not open_day:
        add(1.2, f"water only {d['water_l']} L")
    real = [m for m in day.get("meals", []) if (m.get("kcal") or 0) >= 150 and m.get("time")]
    first = min((m["time"] for m in real), default=None)
    if first and first >= "11:00":
        add(2.5 if hard else 1.3, f"no real breakfast: first meal at {first}"
            + (" on a hard training day" if hard else ""))
    late = [m for m in real if m["time"] >= "22:00"]
    if late:
        add(1, f"late eating: {late[0]['what']} at {late[0]['time']}")
    return {"status": status, "on_target": good,
            "issues_worst_first": [x for _, x in sorted(issues, reverse=True)],
            "log_may_be_incomplete": day.get("meals_logged", 0) <= 2 or (
                not open_day and e.get("kcal", 0) < 0.5 * t.get("kcal", 1))}


def review(payload: dict, user_id: str | None = None) -> DayReview:
    data = payload | {"analysis": analyse(payload)}
    r = llm.complete(name="review-nutrition-day", model=llm.FAST_MODEL, schema=DayReview,
                     user_id=user_id, max_tokens=500, temperature=0.2, messages=[
                         {"role": "system", "content": prompt("c9_day_review")},
                         {"role": "user", "content": to_json(data)}])
    return r.parsed


def cached_review(user_id: str, payload: dict) -> DayReview:
    """The stored review when the day's numbers are unchanged, else a new one (saved)."""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    day, lang = payload["day"], payload["lang"]
    with connection() as c:
        row = c.execute("select input_hash, review from day_reviews where user_id = %s and "
                        "day = %s and lang = %s", (user_id, day, lang)).fetchone()
    if row and row["input_hash"] == digest:
        return DayReview(**row["review"])
    with llm.trace("review-nutrition-day", input=payload, user_id=user_id,
                   tags=["nutrition"]) as root:
        out = review(payload, user_id)
        root.update(output=out.model_dump())
    with connection() as c:
        c.execute("insert into day_reviews (user_id, day, lang, input_hash, review) values "
                  "(%s, %s, %s, %s, %s) on conflict (user_id, day, lang) do update set "
                  "input_hash = excluded.input_hash, review = excluded.review, created_at = now()",
                  (user_id, day, lang, digest, Jsonb(out.model_dump())))
    return out
