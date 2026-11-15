"""C0 Interviewer: 5 synthetic athletes with hidden profiles. A simulated user (LLM) answers only
from the hidden profile. Up to 5 turns. Metrics: slot coverage, slot accuracy (judge), and
redundant questions (asking about a slot that was already known)."""

from statistics import mean

from pydantic import BaseModel

from app import llm
from app.pipeline import interview
from app.pipeline.interview import SLOTS
from evals.common import JUDGE_MODEL, judge, load, run_cases, save

SIM = """You play an athlete answering a coach's setup questions. Answer ONLY with information
from your profile below, briefly, like a real person in a chat, in {lang}. If asked about
something not in the profile, say you don't know. Profile: {profile}"""


class QuestionSlots(BaseModel):
    slots: list[str]


class SlotCheck(BaseModel):
    correct: list[str]
    wrong: list[str]


def simulate(a):
    profile = {k: {"value": v, "source": "intervals"} for k, v in a["prefilled"].items()}
    facts, recent, redundant, asked = [], [], 0, 0
    message = "Давай налаштуємо мій профіль" if a["lang"] == "uk" else "Let's set up my profile"
    for _turn in range(5):
        known_before = set(SLOTS) - set(interview.missing_slots(profile, facts))
        t = interview.interview(message, profile, facts, recent)
        for s in t.filled:
            profile[s.key] = {"value": s.value, "source": "ai"}
        for f in t.facts:
            facts.append({"category": f.category, "text": f.text})
        questions = [q.text for q in t.next_questions]
        recent += [{"role": "user", "content": message},
                   {"role": "assistant", "content": " ".join(questions)}]
        if t.complete or not t.next_questions:
            break
        q = judge("classify-question-slots",
                  f"Which of these slots does each question ask about? Slots: {list(SLOTS)}. "
                  "Return all slots the questions target.", {"questions": questions},
                  QuestionSlots)
        asked += len(q.slots)
        redundant += len([s for s in q.slots if s in known_before])
        reply = llm.complete(name="simulate-user", model=JUDGE_MODEL, max_tokens=300, messages=[
            {"role": "system", "content": SIM.format(lang="Ukrainian" if a["lang"] == "uk"
                                                     else "English", profile=a["hidden"])},
            {"role": "user", "content": " ".join(questions)}])
        message = reply.text
    covered = set(SLOTS) - set(interview.missing_slots(profile, facts))
    filled_values = {k: v["value"] for k, v in profile.items() if k not in a["prefilled"]}
    check = judge("check-slot-values",
                  "Compare the extracted slot values with the true profile. A value is correct "
                  "if it matches in meaning (wording may differ). List slot keys.",
                  {"true_profile": a["hidden"], "extracted": filled_values,
                   "facts": [f["text"] for f in facts]}, SlotCheck)
    return {"coverage": len(covered) / len(SLOTS), "covered": sorted(covered),
            "asked_slots": asked, "redundant": redundant, "turns": len(recent) // 2,
            "correct": check.correct, "wrong": check.wrong}


def main():
    cases = load("c0_interview.jsonl")
    res = run_cases("c0_interview", cases, simulate, workers=5)
    ok = [r for r in res if "error" not in r]
    metrics = {"n": len(cases), "errors": len(res) - len(ok),
               "slot_coverage": round(mean(r["coverage"] for r in ok), 3),
               "slot_accuracy": round(mean(len(r["correct"]) / max(1, len(r["correct"]) + len(r["wrong"]))
                                           for r in ok), 3),
               "redundant_questions": sum(r["redundant"] for r in ok),
               "questions_asked": sum(r["asked_slots"] for r in ok),
               "mean_turns": round(mean(r["turns"] for r in ok), 1)}
    failures = [{"id": c["id"], **r} for c, r in zip(cases, res, strict=True)
                if "error" in r or r["coverage"] < 1 or r["wrong"] or r["redundant"]]
    return save("c0_interview", metrics, failures, {"all": res})


if __name__ == "__main__":
    main()
