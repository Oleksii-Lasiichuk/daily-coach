"""C6 Plan adapter: day type + plan + history + profile -> one workout (or rest).
The validator (validator.py) checks it in code before anything is shown or written."""

from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.pipeline.common import prompt, to_json


class Step(BaseModel):
    kind: Literal["warmup", "work", "recovery", "cooldown", "steady"]
    duration_min: float | None = None
    distance_m: int | None = None
    target: Literal["HR", "Pace", "none"] = "HR"
    zone_low: int | None = Field(default=None, ge=1, le=5)
    zone_high: int | None = Field(default=None, ge=1, le=5)


class Block(BaseModel):
    name: str
    repeats: int = Field(default=1, ge=1, le=30)
    steps: list[Step]


class Workout(BaseModel):
    action: Literal["keep", "modify", "replace", "add", "rest"]
    sport: str
    name: str
    blocks: list[Block]
    rationale: str
    evidence: list[str]


def plan(inputs: dict, feedback: list[str] | None = None, user_id: str | None = None) -> Workout:
    """inputs: {date, day_type, reasons, athlete_sports, planned_today, recent_activities,
    profile, facts, request}. feedback: validator violations from a previous attempt."""
    content = to_json(inputs)
    if feedback:
        content += ("\n\nYour previous proposal broke these rules; fix them:\n- "
                    + "\n- ".join(feedback))
    r = llm.complete(name="plan-workout", schema=Workout, model=llm.SMART_MODEL,
                     user_id=user_id, max_tokens=1200, temperature=0.2, messages=[
                         {"role": "system", "content": prompt("c6_planner")},
                         {"role": "user", "content": content}])
    return r.parsed
