"""C11 Spend category (LLM part): merchants the rules can't place → a category from the fixed
list. Input is merchant description + MCC only (no amount, date or account), one row per
merchant, up to 30 per call. Results are cached per user in merchant_rules (app/money.py)."""

from typing import Literal

from pydantic import BaseModel

from app import llm, spend_rules
from app.pipeline.common import prompt, to_json

BATCH = 30
Category = Literal[tuple(c for c in spend_rules.CATEGORIES
                         if c not in ("transfers", "cash", "income"))]


class Placed(BaseModel):
    merchant: str
    category: Category
    confidence: float


class Placements(BaseModel):
    items: list[Placed]


def inputs(merchants: list[tuple[str, int | None]]) -> list[dict]:
    """What the model sees: names and MCC, nothing else (the eval asserts on this)."""
    return [{"merchant": m[:80], "mcc": mcc} for m, mcc in merchants]


def classify(merchants: list[tuple[str, int | None]], user_id: str | None = None
             ) -> dict[str, tuple[str, float]]:
    """{merchant: (category, confidence)}. A merchant the model skips or renames is left out
    (stays uncategorised, tried again in a later tick)."""
    seen, unique = set(), []
    for m, mcc in merchants:
        if m and m not in seen:
            seen.add(m)
            unique.append((m, mcc))
    out: dict[str, tuple[str, float]] = {}
    for i in range(0, len(unique), BATCH):
        batch = unique[i:i + BATCH]
        r = llm.complete(name="classify-spend", schema=Placements, user_id=user_id,
                         max_tokens=200 + 40 * len(batch), temperature=0, messages=[
                             {"role": "system", "content": prompt("c11_spend")},
                             {"role": "user", "content": to_json(inputs(batch))}])
        names = {m for m, _ in batch}
        for p in r.parsed.items:
            if p.merchant in names:
                out[p.merchant] = (p.category, max(0.0, min(1.0, p.confidence)))
    return out
