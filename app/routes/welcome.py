"""Sign-up in one screen, and the setup cards on Today.

The welcome screen asks only: name, language, main sport, main goal, and what to track. No keys.
Then the app opens. For each thing the person chose, a setup card on Today explains step by step
how to connect it (also in Settings), one card at a time, with "Later".
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import llm, sources, store, weather
from app.auth import current_user
from app.db import connection
from app.pipeline import interview
from app.web import templates, ui

router = APIRouter(dependencies=[Depends(current_user)])
DONE = 6
SPORTS = ["Run", "TrailRun", "Swim", "Ride", "MountainBikeRide", "WeightTraining", "Walk", "Hike",
          "Yoga", "Badminton", "Tennis", "Football", "Rowing", "Ski", "Climbing", "Crossfit"]
NAMES = {"TrailRun": "Trail run", "Ride": "Road cycling", "MountainBikeRide": "MTB",
         "WeightTraining": "Strength", "Swim": "Swimming", "Run": "Running", "Walk": "Walking",
         "Hike": "Hiking", "Ski": "Skiing", "Rowing": "Rowing"}
templates.env.globals["sport_name"] = lambda s: NAMES.get(s, s)
# What the person can choose to track at sign-up (food and water are always on).
TRACKS = [("training", "watch", "Training from my watch",
           "Garmin and others, through intervals.icu"),
          ("weather", "cloud", "Weather where I am", "So runs fit the weather and the air"),
          ("reminders", "bell", "Reminders", "Meals, sleep, medication")]
TRACKS.append(("calendar", "calendar", "My calendar", "So training fits my day"))  # B2
TRACKS.append(("labs", "droplet", "Lab results", "Blood tests and their trends"))  # B3
TRACKS += [("money", "wallet", "Spending", "Monobank and receipts")]  # plan 11 B4


@router.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request, user: store.User = Depends(current_user)):
    if user.setup_step >= DONE:
        return RedirectResponse("/", status_code=303)
    prof = {k: v["value"] for k, v in store.get_profile(user.id).items()}
    sports = prof.get("sports") or []
    return templates.TemplateResponse(request, "welcome.html", {
        **ui(user), "sports": SPORTS, "chosen": sports[0] if sports else "",
        "tracks": TRACKS, "chosen_tracks": user.tracks or ["training", "reminders"],
        "name": user.display_name or "", "city": (prof.get("location") or {}).get("name", ""),
        "city_error": request.query_params.get("error") == "city"})


@router.post("/welcome")
def save_welcome(name: str = Form(""), sport: str = Form(""),
                 goal: str = Form(""), city: str = Form(""), tracks: list[str] = Form([]),
                 user: store.User = Depends(current_user)):
    name = name.strip()[:80]
    if name:
        with connection() as c:
            c.execute("update users set display_name = %s where id = %s", (name, user.id))
    if sport in SPORTS:
        store.set_profile_field(user.id, "sports", [sport], "user", actor="user")
    goal = goal.strip()[:300]
    if goal and not any(f["category"] == "goal" and f["text"] == goal
                        for f in store.list_facts(user.id)):
        store.add_fact(user.id, "goal", goal, "user")
    store.set_tracks(user.id, [t for t, *_ in TRACKS if t in tracks])
    city = city.strip()[:80]
    if city:
        place = weather.geocode(city)
        if not place:
            return RedirectResponse("/welcome?error=city", status_code=303)
        store.set_profile_field(user.id, "location", place, "user", actor="user")
    store.set_setup_step(user.id, DONE)
    return RedirectResponse("/", status_code=303)


@router.post("/welcome/restart")
def restart(user: store.User = Depends(current_user)):
    store.set_setup_step(user.id, 1)
    return RedirectResponse("/welcome", status_code=303)


# --- setup cards (Today) -----------------------------------------------------------------

def setup_cards(user: store.User, has_push: bool, profile: dict) -> list[str]:
    """Which setup cards to offer, in order. Each is shown until done or put off with Later."""
    cards = []
    if "training" in user.tracks and not store.get_secret(user.id, "intervals"):
        cards.append("watch")
    if not all(profile.get(k) for k in ("weight_kg", "height_cm", "birth_year")):
        cards.append("body")
    if "weather" in user.tracks and not profile.get("location"):
        cards.append("location")
    if "reminders" in user.tracks and not has_push:
        cards.append("push")
    if "calendar" in user.tracks and not store.get_secret(user.id, "ical"):
        cards.append("calendar")  # B2
    if "labs" in user.tracks:  # B3
        from app.pipeline import labs
        if not labs.has_any(user.id):
            cards.append("labs")
    if user.tracks and interview.missing_slots(profile, store.list_facts(user.id)):
        cards.append("questions")  # only for people who signed up through the new screen
    if "money" in user.tracks and not store.get_secret(user.id, "monobank"):
        cards.append("money")  # plan 11 B4
    return cards


@router.get("/setup/watch/sheet", response_class=HTMLResponse)
def watch_sheet(request: Request, user: store.User = Depends(current_user)):
    from app.routes.profile import intervals_context
    return templates.TemplateResponse(request, "partials/setup_watch.html",
                                      intervals_context(user))


def _rail(request: Request, user: store.User, **extra):
    """The refreshed side cards (the done setup card disappears)."""
    from app.routes.pages import rail_context
    from app.web import shell
    return templates.TemplateResponse(request, "partials/rail_refresh.html",
                                      shell(user, "/", **rail_context(user), **extra))


@router.post("/setup/body", response_class=HTMLResponse)
def save_body(request: Request, weight_kg: str = Form(""), height_cm: str = Form(""),
              birth_year: str = Form(""), sex: str = Form(""),
              user: store.User = Depends(current_user)):
    for key, val in (("weight_kg", weight_kg), ("height_cm", height_cm),
                     ("birth_year", birth_year)):
        val = val.strip().replace(",", ".")[:10]
        if val:
            store.set_profile_field(user.id, key, val, "user", actor="user")
    if sex in ("M", "F"):
        store.set_profile_field(user.id, "sex", sex, "user", actor="user")
    return _rail(request, user)


@router.post("/setup/city", response_class=HTMLResponse)
def save_city(request: Request, city: str = Form(""), user: store.User = Depends(current_user)):
    place = weather.geocode(city.strip()[:80]) if city.strip() else None
    if place:
        store.set_profile_field(user.id, "location", place, "user", actor="user")
    return _rail(request, user, city_error=not place)


# --- "A few questions from the coach" (C0), optional -------------------------------------

@router.get("/setup/questions", response_class=HTMLResponse)
def questions(request: Request, user: store.User = Depends(current_user)):
    profile, facts = store.get_profile(user.id), store.list_facts(user.id)
    qs, error = [], None
    if interview.missing_slots(profile, facts):
        try:
            files = sources.excerpts(user.id, "injuries illness medication sleep goals races gear")
            qs = interview.interview("(setup form: ask your questions)", profile, facts, [],
                                     user.id, max_questions=5, file_excerpts=files).next_questions
        except llm.LLMError:
            error = "Couldn't prepare the questions. You can tell the coach in the chat instead."
    return templates.TemplateResponse(request, "partials/questions.html",
                                      {**ui(user), "questions": qs, "error": error})


@router.post("/setup/answers")
async def answers(request: Request, user: store.User = Depends(current_user)):
    from starlette.concurrency import run_in_threadpool
    form = await request.form()
    pairs = [f"Q ({k[2:]}): {form.get('q_' + k[2:], '')}\nA: {str(form[k]).strip()}"
             for k in form if k.startswith("a_") and str(form[k]).strip()]
    if pairs:
        await run_in_threadpool(_save_answers, user, "\n\n".join(pairs))
    return RedirectResponse("/", status_code=303)


def _save_answers(user: store.User, text: str) -> None:
    try:
        t = interview.interview(text, store.get_profile(user.id), store.list_facts(user.id), [],
                                user.id, max_questions=0)
    except llm.LLMError:
        return
    for s in t.filled:
        store.set_profile_field(user.id, s.key, s.value, "ai", actor="ai")
    for f in t.facts:
        if f.category in ("goal", "race", "injury", "health", "medication", "gear",
                          "preference", "life"):
            store.add_fact(user.id, f.category, f.text, "ai")
