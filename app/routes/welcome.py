"""First-run window (required before the app opens): 1 Connect intervals.icu · 2 About you ·
3 Goals · 4 Files (optional) · 5 A few questions (C0, optional). 6 = done."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import llm, sources, store
from app.auth import current_user
from app.pipeline import interview
from app.routes.files import files_context
from app.routes.profile import intervals_context
from app.web import templates, ui

router = APIRouter(dependencies=[Depends(current_user)])
DONE = 6
SPORTS = ["Run", "TrailRun", "Swim", "Ride", "MountainBikeRide", "WeightTraining", "Walk", "Hike",
          "Yoga", "Badminton", "Tennis", "Football", "Rowing", "Ski", "Climbing", "Crossfit"]
NAMES = {"TrailRun": "Trail run", "Ride": "Road cycling", "MountainBikeRide": "MTB",
         "WeightTraining": "Strength", "Swim": "Swimming", "Run": "Running", "Walk": "Walking",
         "Hike": "Hiking", "Ski": "Skiing", "Rowing": "Rowing"}
DISTANCES = ["5 km", "10 km", "Half marathon", "Marathon", "Ultra", "Sprint triathlon",
             "Olympic triathlon", "Ironman 70.3", "Ironman", "Bike event", "Swim event", "Other"]
templates.env.globals["sport_name"] = lambda s: NAMES.get(s, s)


def _go(step: int):
    return RedirectResponse("/" if step >= DONE else "/welcome", status_code=303)


def _set(user: store.User, step: int):
    store.set_setup_step(user.id, step)
    return _go(step)


@router.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request, user: store.User = Depends(current_user)):
    step = user.setup_step
    if step >= DONE:
        return RedirectResponse("/", status_code=303)
    prof = {k: v["value"] for k, v in store.get_profile(user.id).items()}
    own = []
    for s in (prof.get("sport_settings") or {}).values():
        own += s.get("types", [])[:1]
    chosen = prof.get("sports") or own
    if isinstance(chosen, str):
        chosen = [x.strip() for x in chosen.split(",")]
    from app.routes.profile import PLAN_SOURCES
    ctx = intervals_context(user, step=step, prof=prof, sports=list(dict.fromkeys(own + SPORTS)),
                            chosen=chosen, distances=DISTANCES, plan_sources=PLAN_SOURCES)
    if step == 4:
        ctx |= files_context(user, setup=True, next_url="/welcome/4/done")
    return templates.TemplateResponse(request, "welcome.html", ctx)


@router.post("/welcome/restart")
def restart(user: store.User = Depends(current_user)):
    return _set(user, 1)


@router.post("/welcome/back")
def back(user: store.User = Depends(current_user)):
    return _set(user, max(1, user.setup_step - 1))


@router.post("/welcome/1")
def step1(user: store.User = Depends(current_user)):
    if not store.get_secret(user.id, "intervals"):
        return _go(1)  # required
    return _set(user, 2)


@router.post("/welcome/2")
async def step2(request: Request, user: store.User = Depends(current_user)):
    form = await request.form()
    for key in ("weight_kg", "height_cm", "birth_year", "sex", "diet", "sleep_target_h",
                "plan_source"):
        val = str(form.get(key, "")).strip()[:80]
        if val:
            store.set_profile_field(user.id, key, val, "user", actor="user")
    sports = [str(s) for s in form.getlist("sports")]
    extra = [s.strip() for s in str(form.get("other_sport", "")).split(",") if s.strip()]
    if sports or extra:
        store.set_profile_field(user.id, "sports", sports + extra, "user", actor="user")
    return _set(user, 3)


@router.post("/welcome/3")
async def step3(request: Request, user: store.User = Depends(current_user)):
    form = await request.form()
    goal = str(form.get("main_goal", "")).strip()[:300]
    if goal:  # goals are items (they live on Training), not a profile field
        store.add_fact(user.id, "goal", goal, "user")
    race, date_, dist = (str(form.get(k, "")).strip()[:120] for k in
                         ("race_name", "race_date", "race_distance"))
    kind, target = str(form.get("race_goal", "finish")), str(form.get("race_target", "")).strip()
    if race:
        details = {"date": date_, "distance": dist, "goal": kind}
        if kind in ("time", "pace") and target:
            details[f"target_{kind}"] = target
        text = f"{race}" + (f" ({dist})" if dist else "") + (f" on {date_}" if date_ else "") + (
            f", target {kind} {target}" if kind in ("time", "pace") and target else ", to finish")
        fid = store.add_fact(user.id, "race", text, "user")
        from psycopg.types.json import Jsonb

        from app.db import connection
        with connection() as c:
            c.execute("update facts set details = %s where id = %s and user_id = %s",
                      (Jsonb(details), fid, user.id))
    body = str(form.get("body_goal", ""))
    if body in ("lose", "gain", "maintain"):
        tgt = str(form.get("body_target", "")).strip()[:10]
        if tgt:
            store.set_profile_field(user.id, "target_weight_kg", tgt, "user", actor="user")
        text = {"lose": "Lose weight", "gain": "Gain weight", "maintain": "Keep weight"}[body] + (
            f" to {tgt} kg" if tgt else "")
        store.add_fact(user.id, "goal", text, "user")
    return _set(user, 4)


@router.post("/welcome/4")
def step4(user: store.User = Depends(current_user)):
    return _set(user, 5)


@router.get("/welcome/4/done")
def step4_done(user: store.User = Depends(current_user)):
    return _set(user, 5)


@router.get("/welcome/questions", response_class=HTMLResponse)
def questions(request: Request, user: store.User = Depends(current_user)):
    profile, facts = store.get_profile(user.id), store.list_facts(user.id)
    qs, error = [], None
    if interview.missing_slots(profile, facts):
        try:
            files = sources.excerpts(user.id, "injuries illness medication sleep goals races gear")
            qs = interview.interview("(setup form: ask your questions)", profile, facts, [],
                                     user.id, max_questions=5, file_excerpts=files).next_questions
        except llm.LLMError:
            error = "Couldn't prepare the questions. You can finish and tell the coach later."
    return templates.TemplateResponse(request, "partials/questions.html",
                                      {**ui(user), "questions": qs, "error": error})


@router.post("/welcome/5")
async def step5(request: Request, user: store.User = Depends(current_user)):
    form = await request.form()
    pairs = [f"Q ({k[2:]}): {form.get('q_' + k[2:], '')}\nA: {str(form[k]).strip()}"
             for k in form if k.startswith("a_") and str(form[k]).strip()]
    if pairs:
        try:
            t = interview.interview("\n\n".join(pairs), store.get_profile(user.id),
                                    store.list_facts(user.id), [], user.id, max_questions=0)
            for s in t.filled:
                store.set_profile_field(user.id, s.key, s.value, "ai", actor="ai")
            for f in t.facts:
                if f.category in ("goal", "race", "injury", "health", "medication", "gear",
                                  "preference", "life"):
                    store.add_fact(user.id, f.category, f.text, "ai")
        except llm.LLMError:
            pass
    return _set(user, DONE)


@router.post("/welcome/finish")
def finish(user: store.User = Depends(current_user)):
    return _set(user, DONE)


