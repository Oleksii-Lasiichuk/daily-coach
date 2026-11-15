"""C5 Day-type assessor: wellness vs baseline + today's logs + facts -> recover/easy/normal/push."""

from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.pipeline.common import prompt, to_json

DayType = Literal["recover", "easy", "normal", "push"]


class Reason(BaseModel):
    text: str
    evidence: str


class Assessment(BaseModel):
    day_type: DayType
    confidence: float = Field(ge=0, le=1)
    summary: str = ""
    reasons: list[Reason]


def assess(inputs: dict, user_id: str | None = None) -> Assessment:
    """inputs: {date, wellness: {today, baseline_7d}, recent_activities, logs, facts}"""
    r = llm.complete(name="assess-day-type", schema=Assessment, model=llm.SMART_MODEL,
                     user_id=user_id, max_tokens=700, temperature=0, messages=[
                         {"role": "system", "content": prompt("c5_daytype")},
                         {"role": "user", "content": to_json(inputs)}])
    return r.parsed


def rule_baseline(inputs: dict) -> str:
    """Non-LLM baseline for the eval: device numbers only (sleep + HRV), ignores what was said."""
    w = inputs.get("wellness")
    if not isinstance(w, dict):
        return "normal"  # no device data: the rule has nothing to go on
    today, base = w.get("today", {}), w.get("baseline_7d", {})
    sleep, hrv, hrv_base = today.get("sleep_h"), today.get("hrv"), base.get("hrv")
    drop = (hrv_base - hrv) / hrv_base if hrv and hrv_base else 0
    if (sleep is not None and sleep < 5) or drop >= 0.15:
        return "recover"
    if (sleep is not None and sleep < 6.5) or drop >= 0.07:
        return "easy"
    if sleep is not None and sleep >= 7.5 and drop <= -0.05:
        return "push"
    return "normal"
