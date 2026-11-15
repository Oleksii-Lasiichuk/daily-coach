"""Pipeline steps the coach agent calls as tools (app/agent.py):
log text → C2 extract → C3 nutrition for meals and drinks → logs;
day → C5 day type → C6 planner → validator → proposal card.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app import history, intervals, llm, sources, store
from app.pipeline import daytype, extract, nutrition, planner
from app.pipeline.validator import to_intervals_text, total_minutes, validate

log = logging.getLogger("turn")
DAY_CHANGING = {"alcohol", "sleep", "pain", "symptom", "planned_workout", "mood"}


@dataclass
class TurnResult:
    reply: str
    trace_id: str | None
    logged: list[dict] = field(default_factory=list)
    assessed: bool = False
    proposal_id: int | None = None


def now_for(user: store.User) -> datetime:
    return datetime.now(ZoneInfo(user.time_zone))


def athlete_context(user: store.User, day: date) -> dict:
    """Compact context for prompts. Never includes secrets or the email."""
    profile = {k: v["value"] for k, v in store.get_profile(user.id).items()}
    facts = store.list_facts(user.id)
    logs = store.logs_between(user.id, day - timedelta(days=1), day)
    return {
        "date": day.isoformat(),
        "profile": profile,
        "facts": [f"{f['category']}: {f['text']}" for f in facts],
        "logs_yesterday_today": [{"day": str(lg["day"]), "kind": lg["kind"], **lg["data"]}
                                 for lg in logs],
        "past_days": history.recent_digests(user.id, day),
    }


def athlete_sports(profile: dict) -> list[str]:
    sports = []
    for s in (profile.get("sport_settings") or {}).values():
        sports += s.get("types", [])
    extra = profile.get("sports")
    if isinstance(extra, str):
        sports += [x.strip() for x in extra.replace(";", ",").split(",") if x.strip()]
    elif isinstance(extra, list):
        sports += extra
    return list(dict.fromkeys(sports + ["WeightTraining", "Walk"]))


def wellness_or_none(user: store.User, day: date) -> dict | None:
    try:
        return intervals.day_snapshot(user.id, day)
    except intervals.IntervalsError as e:
        log.info("no wellness for user %s: %s", user.id, e)
        return None


def assess_and_plan(user: store.User, day: date, request: str, red_flag: bool,
                    result: TurnResult, done: dict, assess: bool = True,
                    plan: bool = True) -> None:
    """C5 then C6 for `day`. assess=False reuses the saved day type (future days get 'normal'
    unless assessed); plan=False stops after C5."""
    ctx = athlete_context(user, day)
    snap = wellness_or_none(user, day)
    inputs = {
        "date": day.isoformat(),
        "wellness": {k: snap[k] for k in ("today", "baseline_7d")} if snap else "not connected",
        "recent_activities": (snap or {}).get("activities_14d", []),
        "logs": ctx["logs_yesterday_today"],
        "facts": ctx["facts"],
        "past_days": ctx["past_days"],
    }
    files = sources.excerpts(user.id, "injuries, illness, medication, health problems. " + request)
    if files:
        inputs["from_user_files"] = files
    saved = store.get_assessment(user.id, day)
    if assess or not saved:
        if assess:
            a = daytype.assess(inputs, user_id=user.id)
            store.save_assessment(user.id, day, a.day_type, a.confidence,
                                  [r.model_dump() for r in a.reasons],
                                  inputs | {"summary": a.summary}, llm.current_trace_id())
            day_type, reasons = a.day_type, [r.text for r in a.reasons]
            done["day_type"] = {"type": a.day_type, "summary": a.summary, "reasons": reasons}
        else:
            day_type = "normal"
            reasons = ["Future day: planned as normal; re-assessed that morning"]
        result.assessed = assess
    else:
        day_type = saved["day_type"]
        reasons = [r["text"] for r in saved["reasons"]]
    if not plan:
        return

    profile = ctx["profile"]
    sports = athlete_sports(profile)
    planned = [lg for lg in ctx["logs_yesterday_today"]
               if lg["kind"] == "planned_workout" and lg["day"] == day.isoformat()]
    injury = any(f.startswith(("injury:", "health:")) for f in ctx["facts"]) or any(
        lg["kind"] in ("symptom", "pain") and lg["day"] == day.isoformat()
        for lg in ctx["logs_yesterday_today"])
    plan_inputs = {
        "date": day.isoformat(), "day_type": day_type,
        "reasons": reasons, "athlete_sports": sports,
        "planned_today": planned or "nothing stated",
        "recent_activities": inputs["recent_activities"],
        "profile": {k: v for k, v in profile.items() if k not in ("name", "location")},
        "facts": ctx["facts"],
        "past_days": ctx["past_days"],
        "red_flag_today": red_flag, "request": request,
    }
    if files:
        plan_inputs["from_user_files"] = files
    from app import weather
    w_day = weather.for_day(profile.get("location"), day)
    if w_day:
        plan_inputs["weather"] = w_day
    feedback = None
    for _attempt in range(2):
        w = planner.plan(plan_inputs, feedback=feedback, user_id=user.id)
        feedback = validate(w, day_type, sports, red_flag=red_flag, injury_or_illness=injury)
        if not feedback:
            break
    if feedback:
        done["workout"] = {"status": "no proposal", "why": feedback}
        return
    workout = w.model_dump() | {"minutes": total_minutes(w), "text": to_intervals_text(w)}
    if planned:
        workout["instead_of"] = "; ".join(p.get("description", "") for p in planned)[:200]
    result.proposal_id = store.add_proposal(user.id, day, workout, w.rationale, w.evidence)
    done["workout"] = {"status": "proposed on a card; the athlete applies it", "action": w.action,
                       "name": w.name, "minutes": workout["minutes"], "sport": w.sport}


def save_logs(user: store.User, ex: extract.Extraction, message_id: int,
              result: TurnResult, done: dict, save_facts: bool = True) -> set[str]:
    kinds = set()
    for ev in ex.events:
        data = ev.model_dump(exclude={"kind", "day", "time"}, exclude_none=True)
        if ev.kind in ("meal", "drink", "alcohol"):  # drinks matter too: caffeine, sugar, alcohol
            try:
                n = nutrition.estimate(ev.description, user_id=user.id)
                data["nutrition"] = n.model_dump()
            except llm.LLMError as e:
                log.warning("nutrition failed: %s", e)
        occurred = None
        if ev.time:
            try:
                h, m = (int(x) for x in ev.time.split(":")[:2])
                occurred = datetime.combine(ev.day, datetime.min.time(),
                                            ZoneInfo(user.time_zone)).replace(hour=h, minute=m)
            except ValueError:
                pass
        store.add_log(user.id, ev.kind, ev.day, data, occurred, message_id)
        kinds.add(ev.kind)
        entry = {"kind": ev.kind, "day": ev.day.isoformat(), "what": ev.description}
        if "nutrition" in data:
            entry["kcal"] = data["nutrition"]["kcal"]
        result.logged.append(entry)
    if save_facts:
        for f in ex.facts:
            store.add_fact(user.id, f.category, f.text, "ai", message_id=message_id)
    done["logged"] = result.logged
    done["facts_saved" if save_facts else "possible_items"] = [
        f"{f.category}: {f.text}" for f in ex.facts]
    return kinds


def assess_only(user: store.User) -> TurnResult:
    """The 'Assess my day' button: C5 + C6 without a chat message."""
    day = now_for(user).date()
    with llm.trace("assess-day", input="assess button", user_id=user.id,
                   session_id=f"{user.id}:{day.isoformat()}", tags=["assess"]) as root:
        result = TurnResult(reply="", trace_id=llm.current_trace_id())
        done: dict = {}
        assess_and_plan(user, day, "What should I do today?", False, result, done)
        root.update(output=done)
    llm.langfuse.flush()
    return result
