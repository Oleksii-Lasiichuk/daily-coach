"""C7 Safety gate: message -> red flag yes/no (high recall)."""

from typing import Literal

from pydantic import BaseModel

from app import llm
from app.pipeline.common import prompt


class Safety(BaseModel):
    red_flag: bool
    category: Literal["none", "cardiac", "neurological", "fever_infection", "injury_severe",
                      "rhabdo_heat", "mental_health", "other"]
    reason: str


def check(message: str, user_id: str | None = None) -> Safety:
    r = llm.complete(name="check-safety", schema=Safety, user_id=user_id, max_tokens=200,
                     temperature=0, messages=[
                         {"role": "system", "content": prompt("c7_safety")},
                         {"role": "user", "content": message}])
    return r.parsed
