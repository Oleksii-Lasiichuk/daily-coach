"""C2 Log extractor: message + local time -> dated events and durable facts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app import llm
from app.pipeline.common import clock, prompt

Kind = Literal["meal", "drink", "alcohol", "sleep", "mood", "pain", "symptom", "medication",
               "activity", "planned_workout", "note"]
FactCategory = Literal["goal", "race", "injury", "health", "medication", "gear", "preference",
                       "life"]


class Event(BaseModel):
    kind: Kind
    day: date
    time: str | None = None
    description: str
    alcohol_drinks: float | None = None
    sleep_hours: float | None = None
    mood_score: int | None = None
    pain_location: str | None = None
    pain_score: int | None = None
    medication_name: str | None = None
    dose: str | None = None
    activity_type: str | None = None
    duration_min: float | None = None
    distance_km: float | None = None


class Fact(BaseModel):
    category: FactCategory
    text: str


class Extraction(BaseModel):
    events: list[Event]
    facts: list[Fact]


def extract(message: str, now: datetime, user_id: str | None = None) -> Extraction:
    user = f"{clock(now)}\n\nMessage:\n{message}"
    r = llm.complete(name="extract-logs", schema=Extraction, user_id=user_id, max_tokens=1200,
                     temperature=0, messages=[
                         {"role": "system", "content": prompt("c2_extract")},
                         {"role": "user", "content": user}])
    return r.parsed
