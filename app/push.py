"""Web push and the scheduled tick (Cloud Scheduler calls /cron/tick every 15 minutes).

Syncs intervals.icu hourly per user. Sends, in each user's time zone: daily nudges (morning
plan, meal reminders, evening check-in; morning and evening have one-tap answers) at the times
set in Settings, and reminders the coach created (e.g. medication); each once per day per time.
Sunday 19:00: the week in numbers. 04:00 local: a health sync and the nightly insight.
"""

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pywebpush import WebPushException, webpush

from app import health, history, intervals, llm, nutrition_stats, store
from app.config import get_settings
from app.db import connection
from app.pipeline import common

log = logging.getLogger("push")
WINDOW_MIN = 15
NUDGE_TEXT = {
    "morning": ("Good morning", "How did you sleep? Open your plan for today."),
    "breakfast": ("Breakfast", "What did you have? A photo is enough."),
    "lunch": ("Lunch", "Log your lunch — text, voice or photo."),
    "dinner": ("Dinner", "Log your dinner to see today's fuel."),
    "evening": ("Evening check-in", "How did today go? Training, food, how you feel."),
}


# One-tap answers (shown as notification buttons where the OS supports them).
QUESTIONS = {
    "morning": ("sleep", [{"action": "bad", "title": "Slept badly"},
                          {"action": "ok", "title": "OK"},
                          {"action": "great", "title": "Slept great"}]),
    "evening": ("feel", [{"action": "tired", "title": "Tired"}, {"action": "ok", "title": "OK"},
                         {"action": "great", "title": "Great"}]),
}
ANSWERS = {("sleep", "bad"): ("sleep", "Sleep felt bad", None),
           ("sleep", "ok"): ("sleep", "Sleep felt OK", None),
           ("sleep", "great"): ("sleep", "Sleep felt great", None),
           ("feel", "tired"): ("mood", "Felt tired in the evening", 2),
           ("feel", "ok"): ("mood", "Felt OK in the evening", 3),
           ("feel", "great"): ("mood", "Felt great in the evening", 4)}


def answer(user_id: str, q: str, a: str) -> bool:
    """Logs a one-tap answer from a notification button."""
    if (q, a) not in ANSWERS:
        return False
    kind, text, mood = ANSWERS[(q, a)]
    user = store.get_user(user_id)
    now = datetime.now(ZoneInfo(user.time_zone))
    data = {"description": text, "source": "notification"} | (
        {"mood_score": mood} if mood else {})
    store.add_log(user_id, kind, now.date(), data, now)
    return True


def send(user_id: str, title: str, body: str, url: str = "/", q: str | None = None,
         actions: list | None = None) -> int:
    s = get_settings()
    if not s.vapid_private_key:
        return 0
    sent = 0
    with connection() as c:
        subs = c.execute("select * from push_subscriptions where user_id = %s",
                         (user_id,)).fetchall()
    for sub in subs:
        try:
            webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"],
                                                             "auth": sub["auth"]}},
                    json.dumps({"title": title, "body": body, "url": url, "q": q,
                                "actions": actions or []}),
                    vapid_private_key=s.vapid_private_key,
                    vapid_claims={"sub": "mailto:noreply@lasiichuk.com"}, ttl=3600)
            sent += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                with connection() as c:
                    c.execute("delete from push_subscriptions where id = %s", (sub["id"],))
            else:
                log.warning("push failed: %s", e)
    return sent


def _due(now_local: datetime, hhmm: str) -> bool:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return False
    t = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    return t <= now_local < t + timedelta(minutes=WINDOW_MIN)


def tick() -> dict:
    stats = {"nudges": 0, "reminders": 0, "insights": 0, "synced": 0, "weekly": 0}
    with connection() as c:
        users = c.execute("select u.*, p.nudges, p.nudges_on from users u left join user_prefs p "
                          "on p.user_id = u.id where u.setup_step >= 6").fetchall()
    for u in users:
        now = datetime.now(ZoneInfo(u["time_zone"]))
        uid = str(u["id"])
        stats["synced"] += health.maybe_sync(uid, now)  # fresh wellness, activities, plan
        if u["nudges_on"] is not False:
            for key, hhmm in (u["nudges"] or {}).items():
                if key in NUDGE_TEXT and _due(now, hhmm) and _mark(uid, f"nudge:{key}", now):
                    title, body = NUDGE_TEXT[key]
                    if key == "morning":
                        a = store.get_assessment(uid, now.date())
                        if a:
                            body = (a["inputs"].get("summary") or body)[:180]
                    q, actions = QUESTIONS.get(key, (None, None))
                    stats["nudges"] += send(uid, title, body, q=q, actions=actions)
        with connection() as c:
            rems = c.execute("select * from reminders where user_id = %s and active and (until is "
                             "null or until >= %s)", (uid, now.date())).fetchall()
        for r in rems:
            for t in r["times"]:
                if _due(now, t) and _mark(uid, f"rem:{r['id']}:{t}", now):
                    stats["reminders"] += send(uid, "Reminder", r["text"])
        if now.weekday() == 6 and _due(now, "19:00") and _mark(uid, "weekly", now):
            w = history.week_review(uid, now.date())["this"]
            body = (f"{w['sessions']} sessions, {w['km']} km, {w['hours']} h"
                    + (f" · sleep {w['sleep_h']} h" if w["sleep_h"] else "")
                    + (f" · alcohol on {w['alcohol_days']} days" if w["alcohol_days"] else ""))
            stats["weekly"] += send(uid, "Your week", body, url="/journal")
        if _due(now, "04:00") and _mark(uid, "insight", now):
            stats["insights"] += daily_insight(uid, now)
    return stats


def _mark(user_id: str, key: str, now: datetime) -> bool:
    """True the first time `key` is seen today (so each nudge goes out once)."""
    return store.mark_once(user_id, key, now.date())


INSIGHT_PROMPT = """You analyse an athlete's last 30 days: daily digests (food, drinks, sleep,
pain, mood, sessions), nutrition averages and wellness trends. Find ONE concrete, useful pattern or
change worth acting on (e.g. how food or alcohol before training relates to how sessions felt,
sleep vs HRV, a nutrient that is often low, a repeated food). Two short sentences in English with
numbers; the second says what to try. If the data is too thin, say what to log to learn more."""


def daily_insight(user_id: str, now: datetime) -> int:
    user = store.get_user(user_id)
    try:
        if store.get_secret(user_id, "intervals"):
            health.sync(user_id, now.date())
    except intervals.IntervalsError:
        pass
    data = {"days": history.recent_digests(user_id, now.date(), 30),
            "nutrition_30d": nutrition_stats.summary(user, now.date(), 30),
            "health_30d": health.summary(user_id, now.date(), 30)}
    if not data["days"]:
        return 0
    try:
        r = llm.complete(name="write-insight", model=llm.SMART_MODEL, user_id=user_id,
                         max_tokens=300, messages=[
                             {"role": "system", "content": INSIGHT_PROMPT},
                             {"role": "user", "content": common.to_json(data)}])
    except llm.LLMError:
        return 0
    store.set_profile_field(user_id, "insight", {"date": now.date().isoformat(),
                                                 "text": r.text.strip()}, "ai", actor="ai")
    return 1
