"""C0 Onboarding interviewer: known profile + facts -> filled slots + next questions."""

from pydantic import BaseModel

from app import llm
from app.pipeline.common import prompt, to_json

# Slot key -> how it can be satisfied besides a profile field (a fact category).
SLOTS = {
    "main_goal": "goal",
    "races": "race",
    "sports": None,
    "weekly_availability": None,
    "injuries_health": "injury",
    "medications": "medication",
    "sleep_target_h": None,
    "height_cm": None,
    "birth_year": None,
    "gear": "gear",
}


class SlotValue(BaseModel):
    key: str
    value: str


class FactOut(BaseModel):
    category: str
    text: str


class Question(BaseModel):
    slot: str
    text: str


class InterviewTurn(BaseModel):
    filled: list[SlotValue]
    facts: list[FactOut]
    next_questions: list[Question]
    complete: bool


def missing_slots(profile: dict, facts: list[dict]) -> list[str]:
    fact_categories = {f["category"] for f in facts}
    return [k for k, cat in SLOTS.items()
            if k not in profile and not (cat and cat in fact_categories)]


def completeness(profile: dict, facts: list[dict]) -> float:
    return round(1 - len(missing_slots(profile, facts)) / len(SLOTS), 2)


def interview(message: str, profile: dict, facts: list[dict], recent: list[dict],
              user_id: str | None = None, max_questions: int = 2,
              file_excerpts: list[str] | None = None) -> InterviewTurn:
    known = {k: v["value"] if isinstance(v, dict) and "value" in v else v
             for k, v in profile.items()}
    payload = {
        "slots": list(SLOTS),
        "empty_slots": missing_slots(profile, facts),
        "known_profile": known,
        "known_facts": [f"{f['category']}: {f['text']}" for f in facts],
        "recent_conversation": [f"{m['role']}: {m['content'][:300]}" for m in recent[-6:]],
        "latest_message": message,
        "max_questions": max_questions,
        "from_user_files": file_excerpts or [],
    }
    r = llm.complete(name="interview-user", schema=InterviewTurn, model=llm.SMART_MODEL,
                     user_id=user_id, max_tokens=800, temperature=0.2, messages=[
                         {"role": "system", "content": prompt("c0_interview")},
                         {"role": "user", "content": to_json(payload)}])
    turn = r.parsed
    turn.filled = [s for s in turn.filled if s.key in SLOTS]
    turn.next_questions = [q for q in turn.next_questions if q.slot in SLOTS][:max_questions]
    return turn
