"""Today: the chat with the coach agent, actions with Undo, session cards, and the side panel
(day, sessions, fuel, insight). Also the Journal (calendar + day pages)."""

import base64
import calendar
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import agent, health, history, i18n, intervals, llm, nutrition_stats, store, weather
from app.auth import current_user
from app.db import connection
from app.pipeline import common
from app.web import shell, templates

router = APIRouter(dependencies=[Depends(current_user)])
log = logging.getLogger("pages")
MAX_IMAGE_BYTES = 4 * 1024 * 1024
RATE_PER_10_MIN = 30


def today_of(user: store.User) -> date:
    return datetime.now(ZoneInfo(user.time_zone)).date()


def profile_value(user_id: str, key: str):
    f = store.get_profile(user_id).get(key)
    return f["value"] if f else None


def next_race(user_id: str, today: date) -> dict | None:
    """The nearest race with a date in the future (from the race items)."""
    best = None
    for f in store.list_facts(user_id):
        if f["category"] != "race":
            continue
        d = (f.get("details") or {}).get("date") or (str(f["until"]) if f["until"] else "")
        try:
            when = date.fromisoformat(str(d)[:10])
        except ValueError:
            continue
        if when >= today and (best is None or when < best["date"]):
            best = {"text": f["text"], "date": when, "days": (when - today).days,
                    "target": (f.get("details") or {}).get("target_time") or
                    (f.get("details") or {}).get("target_pace")}
    return best



# B1: short chip text for each C12 flag (translated in the template).
templates.env.globals["WX_FLAGS"] = {
    "indoors_aqi": "Poor air: intervals indoors", "storm": "Thunderstorm: indoors",
    "rain": "Heavy rain", "ice": "Ice: careful footing", "dark": "Dark: headlamp",
    "uv_high": "Strong sun: sunscreen", "wind": "Strong gusts", "pollen": "High pollen"}

def rail_context(user: store.User) -> dict:
    day = today_of(user)
    connected = store.get_secret(user.id, "intervals") is not None
    # From our synced table, not a live intervals.icu call: the page never waits for it.
    snapshot, wellness_error = (health.day_snapshot(user.id, day) if connected else None), None
    logs = store.logs_between(user.id, day, day)
    a = store.get_assessment(user.id, day)
    suggestion = profile_value(user.id, "meal_suggestion")
    insight = profile_value(user.id, "insight")
    totals = nutrition_stats.day_totals(logs)
    proposals = store.proposals_for_day(user.id, day)
    session_min = max([p["workout"].get("minutes") or 0 for p in proposals
                       if p["status"] != "undone"], default=0)
    profile = store.get_profile(user.id)
    with connection() as c:
        has_push = c.execute("select exists (select 1 from push_subscriptions where user_id = %s)"
                             " as p", (user.id,)).fetchone()["p"]
    from app.routes.welcome import setup_cards
    return {
        "setup": setup_cards(user, has_push, profile),
        "day": day, "connected": connected, "has_push": has_push, "snapshot": snapshot,
        "wellness_error": wellness_error,
        "assessment": a, "proposals": proposals,
        "planned": [lg for lg in logs if lg["kind"] == "planned_workout"],
        "meals": [lg for lg in logs if lg["data"].get("nutrition")],
        "water_l": nutrition_stats.water_l(logs),
        "habits": store.habits_for_day(user.id, day), "race": next_race(user.id, day),
        "weather": weather.for_day((profile.get("location") or {}).get("value"), day),
        "wx": weather.for_user(user.id, day, next((p["workout"].get("sport") for p in proposals
                                                   if p["status"] != "undone"), None),
                               session_min or None),
        "totals": totals, "targets": nutrition_stats.targets(
            user.id, a["day_type"] if a else None, session_min),
        "suggestion": suggestion if isinstance(suggestion, dict) and suggestion.get("date") ==
        day.isoformat() else None,
        "insight": insight if isinstance(insight, dict) else None,
    }


def thread(user: store.User) -> list[dict]:
    msgs = store.recent_messages(user.id, 40)
    acts = agent.actions_for(user.id, [m["id"] for m in msgs if m["role"] == "assistant"])
    props = {}
    for m in msgs:
        for a in acts.get(m["id"], []):
            if a["tool"] == "plan_sessions" and a["undo"]:
                for pid in a["undo"].get("ids", []):
                    p = store.get_proposal(user.id, pid)
                    if p:
                        props.setdefault(m["id"], []).append(p)
    return [m | {"actions": acts.get(m["id"], []), "cards": props.get(m["id"], [])} for m in msgs]


@router.get("/", response_class=HTMLResponse)
def today(request: Request, user: store.User = Depends(current_user)):
    if user.setup_step < 6:
        return RedirectResponse("/welcome", status_code=303)
    health.sync_soon(user.id, datetime.now(ZoneInfo(user.time_zone)))
    with connection() as c:
        day0 = c.execute("select not exists (select 1 from logs where user_id = %s) as d",
                         (user.id,)).fetchone()["d"]
    turn = store.running_turn(user.id)
    # The side cards load right after the page (GET /rail), so the chat shows at once.
    ctx = shell(user, "/", has_rail=True, messages=thread(user), day0=day0, rail_lazy=True,
                turn=turn if turn and turn["status"] == "running" else None)
    return templates.TemplateResponse(request, "today.html", ctx)


# Chat turns run in this pool, not in the request: the reply is saved even if the person opens
# another page, and the page asks for it with GET /chat/turns/{id} (see partials/turn_wait.html).
_turns = ThreadPoolExecutor(max_workers=8, thread_name_prefix="turn")  # a turn + its CPU hold


@router.get("/rail", response_class=HTMLResponse)
def rail(request: Request, user: store.User = Depends(current_user)):
    ctx = shell(user, "/", **rail_context(user))
    return templates.TemplateResponse(request, "partials/rail_refresh.html", ctx)


@router.post("/chat", response_class=HTMLResponse)
def chat(request: Request, text: str = Form(""), mode: str = Form("auto"),
         deep: str = Form(""), images: list[UploadFile] | None = None,
         user: store.User = Depends(current_user)):
    text = text.strip()[:4000]
    lang = store.user_lang(user.id)
    with connection() as c:  # a cap against runaway scripts or a stolen session
        recent = c.execute("select count(*) as n from chat_messages where user_id = %s and "
                           "role = 'user' and created_at > now() - interval '10 minutes'",
                           (user.id,)).fetchone()["n"]
    if recent >= RATE_PER_10_MIN:
        ctx = shell(user, "/", reply_msgs=[], error=i18n.t(
            "Too many messages in a short time. Wait a few minutes.", lang))
        return templates.TemplateResponse(request, "partials/turn.html", ctx)
    if store.running_turn(user.id):
        ctx = shell(user, "/", reply_msgs=[], error=i18n.t(
            "The coach is still answering your last message. Send this one when it's done.",
            lang))
        return templates.TemplateResponse(request, "partials/turn.html", ctx)
    pics = []
    for f in images or []:
        raw = f.file.read(MAX_IMAGE_BYTES + 1)
        if raw and len(raw) <= MAX_IMAGE_BYTES:
            pics.append(raw)
    if not text and not pics:
        return HTMLResponse("")
    attachments = [{"type": "image", "thumb": "data:image/jpeg;base64," +
                    base64.b64encode(p).decode()} for p in pics[:1] if len(p) < 400_000]
    with connection() as c:
        mid = c.execute("insert into chat_messages (user_id, role, content, attachments) values "
                        "(%s, 'user', %s, %s::jsonb) returning id",
                        (user.id, text or "(photo)", common.to_json(attachments))).fetchone()["id"]
    tid = store.start_turn(user.id, mid)
    _turns.submit(_run_turn, tid, user, text, pics, mode, bool(deep), mid, lang)
    _turns.submit(_keep_cpu, tid)
    turn = store.get_turn(user.id, tid)
    return templates.TemplateResponse(request, "partials/turn_wait.html",
                                      shell(user, "/", turn=turn))


def _keep_cpu(tid: int) -> None:
    """Free "scheduler": an open request to this service while the turn runs, so Cloud Run
    (request-based CPU, scale to zero) keeps the instance and its CPU until the reply is saved.
    Needs SELF_URL (set by scripts/deploy) and max one instance, so the request lands here."""
    from app.config import get_settings
    from app.routes.push import cron_secret
    url = get_settings().self_url.rstrip("/")
    if not url or not cron_secret():
        return
    try:
        httpx.post(f"{url}/cron/hold/{tid}", headers={"x-cron-secret": cron_secret()},
                   timeout=200)
    except httpx.HTTPError as e:
        log.info("cpu hold for turn %s ended: %s", tid, e)


def _run_turn(tid: int, user: store.User, text: str, pics: list[bytes], mode: str, deep: bool,
              mid: int, lang: str) -> None:
    """One coach turn in a worker thread; the result is stored in chat_turns."""
    reply, error, r = None, None, {"actions": []}
    try:
        with llm.trace("handle-chat-turn", input=text or "(photo)", user_id=user.id,
                       session_id=f"{user.id}:{today_of(user)}", tags=["chat", mode]) as root:
            try:
                r = agent.run(user, text, pics, mode=mode, deep=deep, message_id=mid)
                reply = r["reply"]
            except llm.BudgetExceeded as e:
                error = str(e)
            except llm.LLMError as e:
                log.warning("chat turn failed: %s", e)
                error = i18n.t("The coach couldn't finish this time. Your message is saved; "
                               "try again.", lang)
            root.update(output=reply or error)
            trace_id = llm.current_trace_id()
        llm.langfuse.flush()
        aid = None
        if reply:
            aid = store.add_message(user.id, "assistant", reply, trace_id)
            agent.save_actions(user.id, aid, r["actions"])
        store.finish_turn(user.id, tid, aid, error)
    except Exception:  # anything else: the turn must not stay "running"
        log.exception("chat turn %s crashed", tid)
        store.finish_turn(user.id, tid, None, i18n.t(
            "The coach couldn't finish this time. Your message is saved; try again.", lang))


@router.get("/chat/turns/{turn_id}", response_class=HTMLResponse)
def chat_turn(request: Request, turn_id: int, user: store.User = Depends(current_user)):
    """Polled by the "Coach is replying…" bubble until the reply is ready."""
    turn = store.get_turn(user.id, turn_id)
    if turn is None:
        return HTMLResponse("", status_code=404)
    if turn["status"] == "running":
        return templates.TemplateResponse(request, "partials/turn_wait.html",
                                          shell(user, "/", turn=turn))
    error = None
    if turn["status"] == "failed":
        error = turn["error"] if turn["error"] != "timeout" else i18n.t(
            "The coach took too long. Your message is saved; try again.", store.user_lang(user.id))
    msg = [m for m in thread(user) if m["id"] == turn["reply_id"]] if turn["reply_id"] else []
    ctx = shell(user, "/", reply_msgs=msg, error=error, **rail_context(user))
    return templates.TemplateResponse(request, "partials/turn.html", ctx)


@router.post("/actions/{action_id}/undo", response_class=HTMLResponse)
def undo_action(request: Request, action_id: int, user: store.User = Depends(current_user)):
    agent.undo(user.id, action_id)
    with connection() as c:
        a = c.execute("select * from agent_actions where id = %s and user_id = %s",
                      (action_id, user.id)).fetchone()
    ctx = shell(user, "/", a=a, **rail_context(user))
    return templates.TemplateResponse(request, "partials/action_undone.html", ctx)


def _card(request: Request, user: store.User, proposal_id: int, error: str | None = None):
    p = store.get_proposal(user.id, proposal_id)
    if p is None:
        return HTMLResponse("This session doesn't exist.", status_code=404)
    ctx = shell(user, "/", p=p, card_error=error)
    return templates.TemplateResponse(request, "partials/session_card.html", ctx)


@router.post("/proposals/{proposal_id}/apply", response_class=HTMLResponse)
def apply_proposal(request: Request, proposal_id: int, user: store.User = Depends(current_user)):
    p = store.get_proposal(user.id, proposal_id)
    if not p or p["status"] not in ("proposed", "undone"):
        return _card(request, user, proposal_id, "This proposal is no longer open.")
    w = p["workout"]
    try:
        event = intervals.create_workout(intervals.connection_for(user.id), p["day"], w["sport"],
                                         w["name"], w["text"])
    except intervals.IntervalsError as e:
        return _card(request, user, proposal_id, str(e))
    store.set_proposal_status(user.id, proposal_id, "applied", str(event["id"]))
    return _card(request, user, proposal_id)


@router.post("/proposals/{proposal_id}/undo", response_class=HTMLResponse)
def undo_proposal(request: Request, proposal_id: int, user: store.User = Depends(current_user)):
    p = store.get_proposal(user.id, proposal_id)
    if not p or p["status"] != "applied":
        return _card(request, user, proposal_id, "Nothing to undo.")
    try:
        intervals.delete_event(intervals.connection_for(user.id), p["intervals_event_id"])
    except intervals.IntervalsError as e:
        return _card(request, user, proposal_id, str(e))
    store.set_proposal_status(user.id, proposal_id, "undone")
    return _card(request, user, proposal_id)


@router.post("/proposals/{proposal_id}/dismiss", response_class=HTMLResponse)
def dismiss_proposal(request: Request, proposal_id: int, user: store.User = Depends(current_user)):
    p = store.get_proposal(user.id, proposal_id)
    if p and p["status"] in ("proposed", "undone"):
        store.set_proposal_status(user.id, proposal_id, "dismissed")
    return _card(request, user, proposal_id)


@router.post("/logs/{log_id}/delete", response_class=HTMLResponse)
def delete_log(request: Request, log_id: int, next: str = Form(""),
               user: store.User = Depends(current_user)):
    store.delete_log(user.id, log_id)
    if safe_next(next):
        return RedirectResponse(next, status_code=303)
    return HTMLResponse("")


def safe_next(url: str) -> bool:
    """Only same-site paths (no open redirects)."""
    return url.startswith("/") and not url.startswith("//") and "\\" not in url


@router.get("/logs/{log_id}/sheet", response_class=HTMLResponse)
def log_sheet(request: Request, log_id: int, next: str = "/nutrition",
              user: store.User = Depends(current_user)):
    lg = store.get_log(user.id, log_id)
    if not lg:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(request, "partials/log_sheet.html", shell(
        user, "/nutrition", lg=lg, next=next if safe_next(next) else "/nutrition",
        labels=nutrition_stats.LABELS, units=nutrition_stats.UNITS))


@router.post("/logs/{log_id}/edit")
def edit_log(log_id: int, next: str = Form("/nutrition"), factor: str = Form(""),
             kcal: str = Form(""), text: str = Form(""),
             user: store.User = Depends(current_user)):
    """Fix a meal: ×½ / ×2 (factor), a kcal you know (scales everything), or new text
    (estimated again)."""
    lg = store.get_log(user.id, log_id)
    back = next if safe_next(next) else "/nutrition"
    if not lg:
        return RedirectResponse(back, status_code=303)
    data = dict(lg["data"])
    old_kcal = nutrition_stats.meal_totals(data).get("kcal") or 0
    try:
        if factor:
            data = nutrition_stats.scale_nutrition(data, max(0.1, min(float(factor), 3)))
        elif kcal and old_kcal:
            data = nutrition_stats.scale_nutrition(data, min(max(0, float(kcal)), 4000)
                                                   / old_kcal)
        elif text.strip() and text.strip() != data.get("description"):
            from app.pipeline import nutrition
            data["description"] = text.strip()[:300]
            if lg["kind"] in ("meal", "drink", "alcohol"):
                data["nutrition"] = nutrition.estimate(data["description"], user.id).model_dump()
    except (ValueError, llm.LLMError):
        return RedirectResponse(back, status_code=303)
    from app.pipeline.turn import implausible
    if implausible(lg["kind"], data):
        return RedirectResponse(back, status_code=303)
    data["edited"] = True
    store.update_log_data(user.id, log_id, data)
    return RedirectResponse(back, status_code=303)


@router.post("/quick/{key}", response_class=HTMLResponse)
def quick_log(request: Request, key: str, user: store.User = Depends(current_user)):
    """One-tap logs next to the chat (water, coffee, tea, beer)."""
    if key not in nutrition_stats.QUICK:
        return HTMLResponse("", status_code=404)
    now = datetime.now(ZoneInfo(user.time_zone))
    kind, data = nutrition_stats.quick_data(key)
    lid = store.add_log(user.id, kind, now.date(), data, now)
    ctx = shell(user, "/", log_id=lid, text=data["description"], **rail_context(user))
    return templates.TemplateResponse(request, "partials/quick_done.html", ctx)


@router.post("/quick/undo/{log_id}", response_class=HTMLResponse)
def quick_undo(request: Request, log_id: int, user: store.User = Depends(current_user)):
    store.delete_log(user.id, log_id)
    ctx = shell(user, "/", **rail_context(user))
    return templates.TemplateResponse(request, "partials/rail_refresh.html", ctx)


@router.post("/habits", response_class=HTMLResponse)
def add_habit(request: Request, name: str = Form(""), user: store.User = Depends(current_user)):
    if name.strip():
        store.add_habit(user.id, name.strip())
    ctx = shell(user, "/", **rail_context(user))
    return templates.TemplateResponse(request, "partials/rail_refresh.html", ctx)


@router.post("/habits/{habit_id}/toggle", response_class=HTMLResponse)
def toggle_habit(request: Request, habit_id: int, user: store.User = Depends(current_user)):
    store.toggle_habit(user.id, habit_id, today_of(user))
    ctx = shell(user, "/", **rail_context(user))
    return templates.TemplateResponse(request, "partials/rail_refresh.html", ctx)


@router.post("/habits/{habit_id}/remove", response_class=HTMLResponse)
def remove_habit(request: Request, habit_id: int, user: store.User = Depends(current_user)):
    store.remove_habit(user.id, habit_id)
    ctx = shell(user, "/", **rail_context(user))
    return templates.TemplateResponse(request, "partials/rail_refresh.html", ctx)


@router.post("/today/assess", response_class=HTMLResponse)
def assess(request: Request, user: store.User = Depends(current_user)):
    from app.pipeline import turn
    error = None
    try:
        turn.assess_only(user)
    except llm.LLMError as e:
        error = str(e)
    ctx = shell(user, "/", rail_error=error, **rail_context(user))
    return templates.TemplateResponse(request, "partials/rail_refresh.html", ctx)


@router.post("/nutrition/suggest", response_class=HTMLResponse)
def suggest_meal(request: Request, user: store.User = Depends(current_user)):
    now = datetime.now(ZoneInfo(user.time_zone))
    meal = ("breakfast" if now.hour < 11 else "lunch" if now.hour < 16 else
            "dinner" if now.hour < 21 else "evening snack")
    data = {"meal": meal, "today": nutrition_stats.summary(user, now.date(), 1),
            "last_14_days": nutrition_stats.summary(user, now.date(), 14),
            "items": [f"{f['category']}: {f['text']}" for f in store.list_facts(user.id)
                      if f["category"] in ("health", "injury", "medication", "preference", "goal")]}
    try:
        messages = [{"role": "system", "content": SUGGEST_PROMPT},
                    {"role": "user", "content": common.to_json(data)}]
        r = llm.complete(name="suggest-meal", model=llm.SMART_MODEL, user_id=user.id,
                         max_tokens=400, messages=messages)
        store.set_profile_field(user.id, "meal_suggestion", {
            "date": now.date().isoformat(), "meal": meal, "text": r.text.strip()}, "ai", actor="ai")
    except llm.LLMError:
        pass
    ctx = shell(user, "/", **rail_context(user))
    return templates.TemplateResponse(request, "partials/rail_refresh.html", ctx)


SUGGEST_PROMPT = """Suggest ONE next meal for the athlete in 1–2 short lines (dish + portion), then
one short line why (which gap it fills). Build it from foods they already eat often
(`last_14_days.top_foods`); avoid repeating what they ate on each of the last 3 days; fill what is
missing today (`today.remaining_today`); respect health items and preferences. Reply in Ukrainian
if their food names are Ukrainian, else English. Plain text, no Markdown headers, no emoji."""


@router.post("/transcribe", response_class=HTMLResponse)
def transcribe(audio: UploadFile, user: store.User = Depends(current_user)):
    """Voice → text with Gemini (Ukrainian and English mixed). The text goes into the box."""
    raw = audio.file.read(8 * 1024 * 1024)
    fmt = "mp4" if "mp4" in (audio.content_type or "") else "webm" if "webm" in (
        audio.content_type or "") else "wav"
    try:
        r = llm.chat(name="transcribe-voice", model=llm.FAST_MODEL, user_id=user.id,
                     max_tokens=800, temperature=0, messages=[{"role": "user", "content": [
                         {"type": "text", "text": "Transcribe this voice note exactly as spoken "
                          "(Ukrainian, English or mixed). Return only the text."},
                         {"type": "input_audio", "input_audio": {
                             "data": base64.b64encode(raw).decode(), "format": fmt}}]}])
        return HTMLResponse((r.choices[0].message.content or "").strip())
    except llm.LLMError as e:
        log.warning("transcribe failed: %s", e)
        return HTMLResponse("", status_code=502)


# --- journal -----------------------------------------------------------------------------

@router.get("/history")
def old_history():
    return RedirectResponse("/journal", status_code=301)


@router.get("/journal", response_class=HTMLResponse)
def journal(request: Request, month: str = "", user: store.User = Depends(current_user)):
    today = today_of(user)
    try:
        first = date.fromisoformat(month + "-01") if month else today.replace(day=1)
    except ValueError:
        first = today.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    data = history.days_between(user.id, first, last)
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    cells: dict[date, dict] = {}
    for r in health.series(user.id, first, last):
        cells.setdefault(date.fromisoformat(r["day"]), {})["sleep"] = r.get("sleep_h")
    for a in health.activities(user.id, first, last):
        c = cells.setdefault(date.fromisoformat(a["day"]), {})
        c["km"] = round(c.get("km", 0) + (a.get("km") or 0), 1)
        c["min"] = c.get("min", 0) + (a.get("minutes") or 0)
    return templates.TemplateResponse(request, "journal.html", shell(
        user, "/journal", first=first, weeks=weeks, data=data, today=today, cells=cells,
        week=history.week_review(user.id, today),
        prev_m=(first - timedelta(days=1)).strftime("%Y-%m"),
        next_m=(last + timedelta(days=1)).strftime("%Y-%m") if last < today else None,
        digests=[(d, history.digest(d, data[d]), history.day_chips(data[d]))
                 for d in sorted(data, reverse=True)]))


@router.get("/day/{day}", response_class=HTMLResponse)
def day_page(request: Request, day: str, user: store.User = Depends(current_user)):
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return RedirectResponse("/journal", status_code=303)
    tz = ZoneInfo(user.time_zone)
    start = datetime.combine(d, datetime.min.time(), tz)
    messages = [m for m in store.recent_messages(user.id, 400)
                if start <= m["created_at"] < start + timedelta(days=1)]
    logs = store.logs_between(user.id, d, d)
    proposals = store.proposals_for_day(user.id, d)
    today = today_of(user)
    from app.routes.data_pages import chart_data
    rows = health.series(user.id, d - timedelta(days=7), d)
    this = next((r for r in rows if r["day"] == d.isoformat()), {})
    before = [r for r in rows if r["day"] < d.isoformat()]
    stats = []
    for key, label, unit, dec in DAY_STATS:
        v = this.get(key)
        vals = [r[key] for r in before if isinstance(r.get(key), (int, float))]
        usual = round(sum(vals) / len(vals), dec or None) if vals else None
        if v is not None:
            stats.append({"key": key, "label": label, "unit": unit,
                          "value": round(v, dec or None), "usual": usual})
    data = chart_data(user.id, min(today, d + timedelta(days=8)), 120)
    return templates.TemplateResponse(request, "day.html", shell(
        user, "/journal", day=d, assessment=store.get_assessment(user.id, d), logs=logs,
        proposals=proposals, messages=messages, stats=stats, data=data,
        acts=health.activities(user.id, d, d), totals=nutrition_stats.day_totals(logs),
        is_future=d > today, today=today, prev_d=d - timedelta(days=1),
        next_d=d + timedelta(days=1), error=request.query_params.get("error")))


DAY_STATS = [("sleep_h", "Sleep", "h", 1), ("sleep_score", "Sleep score", "", 0),
             ("hrv", "HRV", "ms", 0), ("resting_hr", "Resting HR", "bpm", 0),
             ("sleep_hr", "Sleeping HR", "bpm", 0), ("stress", "Stress", "", 0),
             ("readiness", "Readiness", "", 0), ("spo2", "SpO2", "%", 0),
             ("respiration", "Respiration", "brpm", 1), ("steps", "Steps", "", 0),
             ("weight_kg", "Weight", "kg", 1), ("form", "Form", "", 0)]


@router.post("/day/{day}/add")
def day_add(day: str, text: str = Form(""), user: store.User = Depends(current_user)):
    """Add entries to a past day: the extractor reads the text as if said that evening."""
    from app.pipeline import extract
    from app.pipeline.turn import TurnResult, save_logs
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return RedirectResponse("/journal", status_code=303)
    if text.strip() and d <= today_of(user):
        when = datetime.combine(d, datetime.min.time(), ZoneInfo(user.time_zone)).replace(
            hour=21) if d < today_of(user) else datetime.now(ZoneInfo(user.time_zone))
        with llm.trace("add-to-day", input=text, user_id=user.id, tags=["journal"]):
            try:
                ex = extract.extract(f"(All of this happened on {d:%A %d %B %Y}.) " +
                                     text.strip()[:2000], when, user.id)
                for ev in ex.events:
                    ev.day = d
                save_logs(user, ex, None, TurnResult(reply="", trace_id=None), {},
                          save_facts=False)
            except llm.LLMError:
                return RedirectResponse(f"/day/{d}?error=add", status_code=303)
        llm.langfuse.flush()
    return RedirectResponse(f"/day/{d}", status_code=303)


@router.post("/day/{day}/assess")
def day_assess(day: str, user: store.User = Depends(current_user)):
    """Assess any past day (or today) from that day's watch data and logs."""
    from app.pipeline.turn import TurnResult, assess_and_plan
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return RedirectResponse("/journal", status_code=303)
    if d <= today_of(user):
        with llm.trace("assess-day", input=f"assess {d}", user_id=user.id, tags=["assess"]):
            try:
                assess_and_plan(user, d, "assess only", False,
                                TurnResult(reply="", trace_id=None), {}, plan=False)
            except llm.LLMError:
                return RedirectResponse(f"/day/{d}?error=assess", status_code=303)
        llm.langfuse.flush()
    return RedirectResponse(f"/day/{d}", status_code=303)


@router.get("/more", response_class=HTMLResponse)
def more(request: Request, user: store.User = Depends(current_user)):
    return templates.TemplateResponse(request, "more.html", shell(user, "/more"))
