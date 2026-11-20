"""Receipt extraction (part of C11): a receipt photo → Receipt{store, date, total, lines}.

The LLM only reads the photo. Code then: sets each line's category (product keywords, else the
receipt kind's default), adds a remainder line when the lines don't add up to the total
(discounts, unreadable lines), and decides whether to offer "Log as a meal?" (offer_for)."""

import base64
from typing import Literal

from pydantic import BaseModel

from app import llm, spend_rules
from app.pipeline.common import prompt

KIND_DEFAULT = {"restaurant": "eating_out", "grocery": "groceries", "pharmacy": "pharmacy",
                "sport": "sport_gear", "other": "other"}
READY_TO_EAT_MAX_LINES = 5


class Line(BaseModel):
    name: str
    qty: float = 1
    price: float


class Receipt(BaseModel):
    store: str
    date: str | None = None
    total: float
    kind: Literal["restaurant", "grocery", "pharmacy", "sport", "other"] = "other"
    lines: list[Line] = []


def extract(image: bytes, user_id: str | None = None) -> Receipt:
    url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    r = llm.complete(name="read-receipt", schema=Receipt, user_id=user_id, max_tokens=1500,
                     temperature=0, messages=[
                         {"role": "system", "content": prompt("c11_receipt")},
                         {"role": "user", "content": [
                             {"type": "text", "text": "The receipt:"},
                             {"type": "image_url", "image_url": {"url": url}}]}])
    return r.parsed


def categorised_lines(rc: Receipt) -> list[dict]:
    """[{name, qty, amount (₴, positive), category}], summing to the total."""
    default = KIND_DEFAULT[rc.kind]
    out = []
    for ln in rc.lines:
        if ln.price <= 0:
            continue
        cat = spend_rules.product_category(ln.name)
        if rc.kind == "pharmacy" and cat not in ("sports_nutrition",):
            cat = "pharmacy"
        out.append({"name": ln.name[:120], "qty": ln.qty, "amount": round(ln.price, 2),
                    "category": cat or default})
    rest = round(rc.total - sum(x["amount"] for x in out), 2)
    if abs(rest) >= 1:  # a discount or unreadable lines: keep the receipt adding up
        out.append({"name": "other on the receipt" if rest > 0 else "discount", "qty": 1,
                    "amount": rest, "category": default})
    return out


def offer_for(rc: Receipt, lines: list[dict]) -> str | None:
    """'meal' for a restaurant/café or a small ready-to-eat shop purchase, 'fuel' for sports
    nutrition, None for a weekly grocery shop (food bought ≠ food eaten)."""
    cats = [x["category"] for x in lines if x["amount"] > 0]
    if rc.kind == "restaurant" or (cats and all(c in ("eating_out", "coffee") for c in cats)):
        return "meal"
    food = [c for c in cats if c in spend_rules.FOOD]
    if "sports_nutrition" in food and all(c == "sports_nutrition" for c in food):
        return "fuel"
    if (rc.kind == "grocery" and food and len(food) <= READY_TO_EAT_MAX_LINES
            and any(c in ("eating_out", "coffee") for c in food)):
        return "meal"  # e.g. a sandwich and a drink from a shop
    return None
